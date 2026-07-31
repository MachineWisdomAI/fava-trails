# Research: FAVA Trails v0.6.0 and the local Trust Gate benchmark

Research date: 2026-07-31. Primary sources only. This note supports the accompanying Substack draft.

## Thesis

FAVA Trails v0.6.0 moves the judgment boundary—not merely inference—onto the machine that owns the context. A machine can now run the model deciding what becomes durable institutional memory while retaining the existing promotion prompt, fail-closed behavior, audit trail, and shared data model.

The benchmark supports a narrow claim: the tested quantized Qwen3.6 27B model was credible for this promotion-gate task. It was structurally reliable, preserved every historical rejection boundary, and showed a small, conservative net regression after the disagreements were independently adjudicated. It does not establish general parity with Gemini or frontier models.

## Benchmark method

The corpus contained 49 cases:

- 13 unique historical thoughts Gemini had rejected;
- a deterministic, stratified sample of 26 historical thoughts Gemini had approved; and
- 10 prompt-derived canaries: four positive controls and six rejection cases.

The replay constructed the production FAVA Trust Gate messages, including XML-escaped thought bodies and redacted metadata, and used FAVA's production verdict parser. Historical Gemini decisions were comparison references, not a fresh rerun or unquestionable ground truth. Eight representative cases were repeated three times, and two short requests were also tested concurrently.

Primary evidence: [issue #85 benchmark comment](https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500).

## Results

| Measure | Result |
|---|---:|
| Valid structured verdicts | 49/49 |
| Parse, CLI, or retry failures | 0 |
| Raw agreement with references and canaries | 39/49 (79.6%) |
| Historical rejections matched | 13/13 |
| Historical approvals matched | 17/26 |
| Canaries matched | 9/10 |
| Repeat consistency | 8/8 stable across three runs |
| Median / p95 / maximum latency | 14.0s / 122.9s / 172.5s |

All ten disagreements were additional local-model rejections. No permissive error was observed against the 13 historical rejection cases in this corpus.

The nine historical disagreements were independently re-audited against the exact prompt. Gemini's approval was judged better in six cases; the local rejection was judged better in three. The separate tenth disagreement was an over-rejected positive canary. The historical comparison therefore produced a net regression of three judgments, not nine. This is an interpretive adjudication, not a formal accuracy estimate.

## Important limitations

- Call 79.6% raw agreement, not accuracy.
- The corpus is focused and historical Gemini was not rerun.
- Inputs above 40,000 characters achieved only 2/6 agreement and had 122.9-second median latency.
- Disagreement confidence averaged 0.93, so confidence did not reveal over-strict judgments.
- Repeat stability covered eight selected cases, not the entire corpus.
- “No permissive error was observed” must not become “the model cannot make false approvals.”

## What v0.6.0 shipped

- Provider-neutral OpenAI-compatible Trust Gate configuration.
- Standard per-machine config at `$XDG_CONFIG_HOME/fava-trails/config.yaml`.
- Separation of machine-specific runtime choices from shared trail configuration.
- Owner-only, non-symlink credential files with per-promotion rereads and one changed-key retry after a 401.
- Provider-specific request controls without an Unsloth-specific SDK or transport.
- Provider/model provenance and consistent effective configuration across MCP promotion, doctor, readiness, and tunnel preflight.
- Backward-compatible OpenRouter defaults and no automatic hosted fallback after local failure.

Primary sources: [v0.6.0 release](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.6.0), [issue #85](https://github.com/MachineWisdomAI/fava-trails/issues/85), [implementation PR #87](https://github.com/MachineWisdomAI/fava-trails/pull/87), and [release PR #88](https://github.com/MachineWisdomAI/fava-trails/pull/88).

## May–July product arc

- [v0.5.6](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.6): hardened the hosted OpenRouter response boundary.
- [v0.5.7](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.7): blocked unsafe sync and commits when Git/JJ data was dirty, case-colliding, or unexpectedly changed.
- [v0.5.8](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.8): added human-readable rich views, a ChatGPT secure-tunnel gateway, MCP output schemas, structured error preservation, safer scope lookup, and tunnel lifecycle hardening.
- [v0.5.9](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.5.9): added bounded fail-closed tunnel readiness and stabilized the runtime dependency boundary.
- [v0.6.0](https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.6.0): made local promotion gating a supported per-machine operating mode.

Between v0.5.6 on 2026-05-05 and v0.6.0 on 2026-07-31, the repository recorded 66 commits across 45 changed files. Earlier public packaging and lifecycle-hook releases are useful background but fall outside the strict three-month window.
