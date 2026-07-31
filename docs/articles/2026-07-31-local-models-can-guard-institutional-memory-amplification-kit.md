# Amplification kit: FAVA Trails v0.6.0 local Trust Gate

This file contains copy for manual publishing. Copy only the text inside the relevant block. Younes publishes each item and makes the final platform-specific formatting choice.

## Links

Clean links are for durable owned surfaces:

- Article: https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides
- FAVA Trails v0.6.0: https://github.com/MachineWisdomAI/fava-trails/releases/tag/v0.6.0
- Benchmark evidence: https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500
- PyPI: https://pypi.org/project/fava-trails/0.6.0/

Tracked article links are for social posts:

| Destination | URL |
|---|---|
| Personal LinkedIn | https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=personal-post |
| Company LinkedIn | https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=company-reshare |
| Substack Note | https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=substack&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=note |
| r/LocalLLaMA | https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=reddit&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=rlocalllama |

## Personal LinkedIn

### Primary

```text
I maintain FAVA Trails, an open-source, Git-native memory system for AI agents.

Version 0.6.0 lets the model that decides which drafts become permanent run locally through an OpenAI-compatible endpoint. I tested that path with a quantized Qwen3.6 27B model and the exact prompt FAVA uses in production.

Across 49 historical cases and canaries, the model returned 49 valid verdicts. It matched all 13 historical rejections, 17 of 26 historical approvals, and 9 of 10 canaries.

The direction of the errors mattered more to me than the aggregate agreement rate. Every disagreement was an additional rejection. A rejected thought stays visible as a draft and can be revised. A bad approval quietly enters institutional memory and can steer later agents.

I asked OpenAI Codex running GPT 5.6 to review the nine historical disagreements against the same prompt. It favored Gemini in six cases and the local model in three. That is not independent ground truth, but it made the tradeoff concrete: the local model was stricter, sometimes too strict, and never crossed a historical rejection boundary in this corpus.

For this task, that is an error profile I am willing to operate. Promotion candidates can stay on the local machine, per-thought hosted inference fees disappear, and a hosted provider leaves the critical path.

The benchmark, limitations, and implementation details are here:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=personal-post
```

### Short

```text
FAVA Trails v0.6.0 can use a local model to decide what deserves permanent agent memory.

I tested a quantized Qwen3.6 27B model on 49 historical cases and canaries: 49/49 valid verdicts, 13/13 historical rejections preserved, 17/26 approvals matched, and 9/10 canaries matched.

A second-model review favored Gemini on six historical disagreements and the local model on three. The local model was stricter, but its errors were conservative and recoverable. For the memory gate I maintain, that tradeoff works.

Results and limitations:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=personal-post
```

## Machine Wisdom AI LinkedIn reshare

Reshare the personal post from the company page on the following day. Use one introduction above the reshare.

### Primary

```text
FAVA Trails v0.6.0 adds provider-neutral local-model gating for permanent agent memory.

The release is backed by a 49-case test of the production promotion prompt: 49 valid verdicts, all 13 historical rejection boundaries preserved, and a conservative error profile that keeps questionable material in drafts instead of quietly promoting it.

Younes explains the benchmark, the six-versus-three disagreement review, and the limits of the evidence in the post below.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=company-reshare
```

### Short

```text
FAVA Trails v0.6.0 can keep agent-memory promotion review on the operator's machine.

The 49-case benchmark produced valid verdicts every time and preserved all 13 historical rejection boundaries. Read the results, disagreements, and limitations below.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=company-reshare
```

## Substack Note

### Primary

```text
I tested a quantized Qwen3.6 27B model as the local promotion gate for FAVA Trails.

The model returned valid verdicts in all 49 cases, preserved all 13 historical rejections, matched 17 of 26 historical approvals, and matched 9 of 10 canaries.

A second-model review of the nine historical disagreements favored Gemini in six cases and the local model in three. The local model was stricter, but every observed error was an additional rejection, which leaves the thought visible and recoverable as a draft.

The benchmark and its limits:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=substack&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=note
```

### Short

```text
Local-model memory gating in FAVA Trails: 49/49 valid verdicts, all 13 historical rejections preserved, and a six-versus-three disagreement review that showed where the local model was too strict and where it caught weak promotions.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=substack&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=note
```

## r/LocalLLaMA

Check https://www.reddit.com/r/LocalLLaMA/about/rules/ immediately before posting. If a benchmark post with a maintainer disclosure and links would violate the current rules, skip it. Do not remove the disclosure or disguise the links.

### Primary title

```text
I tested a quantized Qwen3.6 27B model as a local gate for agent memory: 49 cases, all 13 historical rejections preserved
```

### Primary body

```markdown
Disclosure: I maintain FAVA Trails, the open-source project I tested here.

FAVA Trails stores agent memory as versioned Markdown in Git. Draft thoughts go through a promotion gate before they become permanent memory. Version 0.6.0 lets that gate use a local model through an OpenAI-compatible endpoint, so I wanted to know whether a quantized model was reliable enough for this specific job.

I tested `unsloth/Qwen3.6-27B-GGUF` through Unsloth Studio with the exact production promotion prompt. The corpus contained 39 historical thoughts with prior Gemini verdicts, including 26 approvals and 13 rejections, plus 10 synthetic canaries.

The historical Gemini verdicts were references from earlier operation, not a fresh Gemini rerun.

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

Every disagreement was an additional rejection by the local model. It did not reverse any of the 13 historical Gemini rejections in this corpus.

That error direction fits a promotion gate. A false rejection leaves the thought in drafts, where it can be revised and resubmitted. A false approval quietly adds weak material to future agent context.

The local model rejected nine historical thoughts Gemini had approved. I asked OpenAI Codex running GPT 5.6 to judge those nine against the same production prompt. It favored Gemini in six cases and the local model in three. In those three, the local model caught a transient handoff, a misclassified implementation artifact, and an imperative task instruction that lacked durable rationale. A separate positive canary accounted for the tenth disagreement.

That second-model review is an interpretive challenge to the old verdicts, not independent ground truth. The test covers one model, one prompt, and one corpus. It does not show general parity with Gemini or frontier models.

Long inputs were the weak spot. Inputs over 40,000 characters reached only 2/6 raw agreement and had a median latency of 122.9 seconds. The model was also confident when wrong, so confidence is not a useful escalation trigger by itself.

My conclusion is narrow: this quantized model had an acceptable, conservative error profile for this promotion policy. The released integration remains provider-neutral and fails closed if the local endpoint is unavailable or returns malformed output.

Full write-up:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=reddit&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=rlocalllama

Benchmark evidence and disagreement audit:
https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500
```

### Short title

```text
Local Qwen3.6 27B as an agent-memory gate: 49/49 valid verdicts and 13/13 historical rejections preserved
```

### Short body

```markdown
Disclosure: I maintain FAVA Trails, the open-source project I tested here.

FAVA Trails v0.6.0 can use a local OpenAI-compatible model to review drafts before they enter permanent agent memory. I tested `unsloth/Qwen3.6-27B-GGUF` through Unsloth Studio with the exact production prompt.

The corpus contained 39 historical thoughts with prior Gemini verdicts and 10 synthetic canaries. The Gemini verdicts were historical references, not a fresh rerun.

| Measure | Result |
|---|---:|
| Valid verdicts | 49/49 |
| Raw agreement | 39/49 |
| Historical rejections matched | 13/13 |
| Historical approvals matched | 17/26 |
| Canaries matched | 9/10 |
| Repeat consistency | 8/8 cases stable across three runs |

Every disagreement was an additional rejection. A second-model review of the nine historical disagreements favored Gemini in six cases and the local model in three. The tenth disagreement was a positive canary. That review is not independent ground truth, but it shows the error direction clearly: the local model was conservative, sometimes too conservative, and did not cross a historical rejection boundary in this corpus.

The result is limited to one model, prompt, and corpus. Inputs over 40,000 characters were weak at 2/6 raw agreement with 122.9-second median latency, and confidence did not identify bad verdicts.

Full method and limitations:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=reddit&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=rlocalllama

Evidence:
https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500
```

## GitHub v0.6.0 release addition

Append this to the existing release body using the clean canonical URL:

```markdown
### Benchmark write-up

[FAVA Trails v0.6.0: The Model That Decides What Our Agents Remember Now Runs Locally](https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides) covers the 49-case evaluation, disagreement review, and limits of the local-model promotion gate.
```

## Manual publishing order

1. Add the benchmark write-up to the GitHub v0.6.0 release.
2. Publish the personal LinkedIn post.
3. Publish the Substack Note.
4. Review and merge the separate machine-wisdom.ai indexing PR.
5. On the following day, reshare the personal LinkedIn post from the Machine Wisdom AI page.
6. Recheck the live r/LocalLLaMA rules, then publish or skip the Reddit post.
7. Record each public URL and the first measurement checkpoint in the measurement ledger.
