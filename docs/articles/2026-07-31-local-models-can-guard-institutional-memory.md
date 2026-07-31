# FAVA Trails v0.6.0: The Model That Decides What Our Agents Remember Now Runs Locally

## FAVA Trails v0.6.0 brings local-model promotion gating. Our benchmark found that a quantized Qwen model was conservative, consistent, and good enough for the job

The newest release of [FAVA Trails](https://github.com/MachineWisdomAI/fava-trails), v0.6.0, can use a local OpenAI-compatible model to decide which agent memories deserve to become permanent.

That means a thought being considered for institutional memory no longer has to be sent to OpenRouter, Gemini, or another hosted model. The review can happen on the operator's own machine, while OpenRouter remains the default for people who prefer it.

A quantized local model still has to be trustworthy enough to act as the gatekeeper.

We ran [49 historical cases and canaries](https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500) through an Unsloth-served Qwen3.6 27B GGUF model. It returned valid structured verdicts in all 49 cases, preserved all 13 historical rejection boundaries in the corpus, and was stable across every repeated case. Every observed disagreement was conservative: the local model rejected additional material, but it did not reverse any of the 13 historical Gemini rejections.

I then asked OpenAI Codex to re-audit the disagreements as a second-model adjudicator. The local model's interpretive net difference against the historical Gemini references was only three judgments. In exchange, promotion candidates in the Mac-local deployment stay local, per-thought hosted API fees disappear, and a hosted provider is removed from the critical path.

For this job, that is a trade I am willing to make.

## The hard part is deciding what deserves to become memory

Agents generate a lot of text. Most of it should not become durable context.

A useful observation, a decision with rationale, or a hard-won negative result may help the next agent. Process narration, transient runtime state, unsupported claims, and instructions disguised as facts usually will not. If all of it is saved indiscriminately, “memory” becomes a larger context window full of noise and contradictions.

FAVA Trails (short for Federated Agents Versioned Audit Trail) treats memory as curated, versioned knowledge rather than a transcript archive. Thoughts begin as drafts. A promotion gate reviews them before they enter permanent namespaces. Superseded beliefs remain in the audit history but disappear from normal recall. Every record is a Markdown file with structured metadata in a Git repository controlled by the operator, with Jujutsu handling atomic changes underneath.

The Trust Gate asks a deliberately simple question:

> Will a future agent, with no context about this conversation, find this thought useful?

The [production review prompt](https://github.com/MachineWisdomAI/fava-trails/blob/v0.6.0/src/fava_trails/data_repo_template/trust-gate-prompt.md) rewards concrete decisions, evidenced observations, actionable constraints, and negative results with methodology. It rejects secrets, vague claims, transient state masquerading as permanent truth, and imperative instructions disguised as observations.

Before v0.6.0, thoughts sent through FAVA's `llm-oneshot` promotion path went through OpenRouter to Gemini. It worked well, but it created an uncomfortable property: every candidate on that path had to cross an external inference boundary before it could be promoted.

## What we benchmarked

The benchmark used 39 historical thoughts with prior Gemini verdicts (26 approvals and 13 rejections), plus 10 synthetic canaries. The local candidate was the quantized model exposed as `unsloth/Qwen3.6-27B-GGUF` through Unsloth Studio on the workstation.

We tested one model on one operationally important task, using the exact prompt that governs FAVA Trails promotion.

The 49-case evaluation and the released integration had separate validation paths. The benchmark used WisdomHelm's provider-neutral `local-llm` CLI to send FAVA's exact production messages and parse the results with FAVA's production verdict parser; it did not change the production provider configuration or exercise the new v0.6 provider path end to end. After the release was integrated, [a separate live dogfood](https://github.com/MachineWisdomAI/fava-trails/pull/88) exercised that provider path directly: it approved a durable architectural decision and rejected an adversarial instruction.

The results were:

| Measure | Result |
|---|---:|
| Valid structured verdicts | 49/49 |
| Parse, CLI, or retry failures | 0 |
| Raw agreement with historical references and canaries | 39/49 (79.6%) |
| Historical rejections matched | 13/13 |
| Historical approvals matched | 17/26 |
| Canaries matched | 9/10 |
| Repeat consistency | 8/8 cases stable across three runs |
| Median latency | 14.0 seconds |
| p95 latency | 122.9 seconds |
| Maximum latency | 172.5 seconds |

Raw agreement was 79.6%, which sounds merely adequate until you look at the direction of the errors.

Every disagreement was an additional rejection by the local model. Among the 13 historical Gemini rejections in this corpus, it did not reverse a single verdict. That matters because the cost of the two error types is asymmetric:

- A false rejection is visible and recoverable. The thought remains a draft, can be improved, and can be resubmitted.
- A false approval is quiet. Low-quality material enters institutional memory, consumes future context, and may steer later agents.

A conservative critic is often preferable to a permissive one.

## What the nine disagreements revealed

The local model rejected nine historical thoughts Gemini had approved. Rather than treating Gemini as ground truth, I asked OpenAI Codex, separate from the quantized candidate, to judge each thought against the exact promotion prompt. This second-model review was a structured challenge to the historical verdicts, not independent human ground truth. It is published with the other [evaluation evidence](https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500).

Gemini had the better verdict in six cases. The local model was simply too strict.

But in three cases, the local model caught material Gemini should not have promoted:

1. A transient builder-state handoff had been stored as a permanent review.
2. An implementation-heavy artifact had been misclassified as a specification.
3. An imperative task instruction had been presented as durable knowledge without provenance or rationale.

So the historical disagreement set contained six lost approvals and three improved rejections: an interpretive net difference of three judgments after second-model adjudication, not a formal accuracy estimate. The tenth disagreement was a separate positive canary that the local model also rejected too conservatively.

The evidence supports a small, understandable quality difference on this task, tilted in the safer direction. It is too narrow to establish that the local model is better than Gemini overall.

The full evidence and caveats are recorded in [FAVA Trails issue #85](https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500).

## The limits of the benchmark

The benchmark supports one bounded conclusion: this local model had an acceptable error profile for FAVA's promotion prompt on this corpus. It does not establish general parity with Gemini, frontier models, or unrelated agent tasks.

The Gemini verdicts were historical references, not a fresh Gemini rerun. The benchmark covered a specific corpus and prompt, not arbitrary reasoning tasks. Long inputs were a weak spot: inputs over 40,000 characters achieved only 2/6 raw agreement and had a median latency of 122.9 seconds. The largest successful request contained 29,397 prompt tokens.

The local model was also confidently wrong when it was wrong. Its average confidence on disagreements was 0.93, so confidence is not a reliable trigger for escalation. Occasional sampling and verdict logging remain useful for detecting drift.

Task-specific evaluation makes this decision possible because it asks whether this model enforces this promotion policy with an acceptable error profile. For FAVA Trails, the answer was yes.

## The implementation stays provider-neutral

[FAVA Trails v0.6.0](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.6.0) supports local promotion gating through a provider-neutral OpenAI-compatible interface. Although Unsloth Studio was the first live target, the release does not contain an Unsloth-specific SDK or transport.

Each machine can select its provider, exact model identifier, API base, timeout, credentials, and provider-specific request controls through the standard per-machine configuration at `~/.config/fava-trails/config.yaml`. Shared trail configuration does not need to change, so one workstation can use a local model while another machine or a ChatGPT gateway continues using OpenRouter.

Credentials follow the same fail-closed rules. File-backed API keys must be owner-only regular files; symlinks are rejected. The key is reread for every promotion, and an authentication failure gets one retry only if the key actually changed. The MCP server, doctor, readiness checks, and tunnel preflight all resolve the same effective configuration.

Failures remain fail-closed. If the local endpoint is unavailable, times out, rejects authentication, or returns malformed output, FAVA Trails does not silently fall back to a hosted provider and promote the thought anyway.

Failing closed reduces external dependency without creating an invisible alternate decision path.

## FAVA Trails changed substantially in the last few months

From May through July, FAVA Trails added four operational layers around its memory core: safer synchronization, human-readable views, authenticated ChatGPT access, and local promotion gating. The local Trust Gate is the v0.6.0 headline, but it rests on that broader push to make agent memory inspectable, portable, and operationally safe.

Between [v0.5.6 and v0.6.0](https://github.com/MachineWisdomAI/fava-trails/compare/v0.5.6...v0.6.0), May 5 through July 31, the repository accumulated 66 commits. The public milestones also included [v0.5.7](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.7), [v0.5.8](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.8), and [v0.5.9](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.9).

### Data integrity became fail-closed

[FAVA Trails v0.5.7](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.7) made data integrity fail-closed. FAVA sync now blocks when the data repository has a dirty working copy or case-colliding tracked paths, while commit operations fail fast on unexpected changes and executable-bit churn. This protects the memory store from subtle VCS mistakes that are easy for agents to miss.

### Memory became visible to humans

[FAVA Trails v0.5.8](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.8) made agent memory directly inspectable. Its rich-view commands generate and serve a small Astro reader from trail records, with stable ULID routes, derived titles, and snapshot metadata. It is intentionally a reader rather than another editing surface: humans can inspect what agents saved without bypassing the MCP lifecycle that governs changes.

### FAVA reached ChatGPT without exposing an unauthenticated public MCP endpoint

The v0.5.8 ChatGPT tunnel gateway made FAVA reachable from an authorized ChatGPT client without publishing an unauthenticated MCP endpoint. It runs a private loopback MCP runtime behind an authenticated secure tunnel, with detached lifecycle commands and a bounded `/healthz` readiness probe. Authorized requests can receive returned FAVA data through that tunnel, while structured MCP errors and output schemas survive the gateway boundary.

Tunnel startup was hardened over several releases. Readiness checks validate that the runtime identity can actually traverse the configured trail tree and parse representative data. Optional startup sync is bounded and fail-closed. Recurring autosync is disabled by default rather than quietly mutating shared state.

### Read operations stopped having write-shaped side effects

Read-only calls no longer create missing scopes. Exact-ULID lookup can find a unique thought across scopes and reports its source trail. Supersession preserves an existing confidence value when callers omit a replacement. These sound like small details; together, they make the system behave more like a dependable knowledge substrate and less like an optimistic demo.

### Packaging and provider compatibility received production attention

OpenRouter response compatibility was hardened in May. The MCP dependency was later constrained to the supported 1.x line so a fresh resolution could not select an incompatible major and crash the server before initialization. The v0.6.0 release itself passed 755 tests, Ruff, Semantic PR validation, and CodeQL before being published to PyPI through trusted publishing.

## Why this task fits a local model

Local models are strongest when the task has a stable policy, structured output, auditable historical cases, and asymmetric failure costs. FAVA's promotion gate has all four.

For this kind of task, we can measure the model on the real job, inspect every disagreement, and decide whether its mistakes are acceptable. In this benchmark, I consider them acceptable.

The local model preserved every historical rejection boundary, produced valid JSON every time, behaved consistently under repetition, and caught three approvals that deserved another look. It approved fewer historically approved candidates in exchange for keeping promotion payloads off hosted inference, eliminating per-thought hosted API fees, and reducing provider dependence.

[FAVA Trails v0.6.0](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.6.0) is available now on [PyPI](https://pypi.org/project/fava-trails/0.6.0/). The project is open source under Apache 2.0.
