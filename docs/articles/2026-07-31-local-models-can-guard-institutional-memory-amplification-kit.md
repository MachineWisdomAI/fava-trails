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
Agents generate a lot of text, and most of it should not become durable context. A useful observation, a decision with its rationale, or a hard-won negative result may help the next agent, but process narration and transient runtime state usually will not. When everything is saved indiscriminately, "memory" becomes a larger context window full of noise and contradictions that steer later agents wrong.

FAVA Trails, the open-source Git-native memory system I maintain, treats memory as curated, versioned knowledge rather than a transcript archive. Every thought begins as a draft, and a trust gate reviews it by asking whether a future agent, with no context about this conversation, would find it useful. Only the thoughts that pass become permanent memory, while superseded beliefs remain in the audit history but disappear from normal recall.

Until v0.6.0, that review had to travel through a hosted model, so every candidate memory crossed an external inference boundary before it could be promoted. The gate can now run on the operator's own machine through any OpenAI-compatible endpoint, which keeps promotion candidates local, eliminates per-thought hosted API fees, and removes a hosted provider from the critical path.

Before trusting a quantized model with that job, I benchmarked an Unsloth-served Qwen 3.6 27B against 49 historical promotion decisions that carried prior Google Gemini verdicts. It proved on par with Gemini for this task, and its mistakes leaned in the safe direction: every disagreement was an additional rejection, which leaves the thought visible as a draft where it can be revised and resubmitted, rather than a quiet approval that lets weak material into institutional memory. It approved somewhat fewer historical candidates in exchange for keeping promotion review local, and for this job that is a trade I am willing to make.

The full benchmark, the disagreement audit, and the limitations are in the write-up:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=personal-post
```

### Short

```text
The hard part of agent memory is deciding what deserves to be remembered, and FAVA Trails v0.6.0 lets that decision happen on your own machine. A local model can now review every draft thought before it becomes permanent, versioned memory, so promotion candidates stay local and no hosted provider sits in the critical path.

I benchmarked an Unsloth quantized Qwen 3.6 model against the gate's historical Google Gemini verdicts, and it proved on par with Gemini for this job. Its errors were conservative and recoverable: every mistake was an extra rejection that leaves the thought editable as a draft, rather than a quiet approval that pollutes permanent memory.

The results and their limitations:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=personal-post
```

## Machine Wisdom AI LinkedIn reshare

Reshare the personal post from the company page on the following day. Use one introduction above the reshare.

### Primary

```text
FAVA Trails, our open-source Git-native memory system, reviews every draft thought before it becomes permanent agent memory, and with v0.6.0 that review can run entirely on the operator's machine.

Younes benchmarked an Unsloth quantized Qwen 3.6 model against the gate's historical Google Gemini verdicts and found it on par with Gemini for this job, with mistakes that lean toward rejecting too much rather than approving too much. He explains below why that is the right failure profile for a memory gate.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=company-reshare
```

### Short

```text
FAVA Trails v0.6.0 moves agent-memory review onto the operator's machine. Draft thoughts still pass the Trust Gate before becoming permanent memory, but the gate can now be a local model, so no hosted provider sits in the critical path. The benchmark and its limitations are below.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=linkedin&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=company-reshare
```

## Substack Note

### Primary

```text
Agents produce endless text, and almost none of it deserves to be remembered. FAVA Trails, the memory system I maintain, makes every thought earn its permanence: a thought begins as a draft, a trust gate asks whether a future agent with no context about the conversation would find it useful, and only the thoughts that pass become permanent, versioned memory.

As of v0.6.0 that gate can run on a local model. I benchmarked an Unsloth quantized Qwen 3.6 model on 49 historical promotion decisions to see whether it could be trusted with the job, and it proved on par with the Google Gemini verdicts it replaced. Its mistakes were conservative ones: every error was an extra rejection that stays recoverable as a draft, and it never quietly approved weak material into permanent memory.

The benchmark and its limits:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=substack&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=note
```

### Short

```text
The model that decides what our agents remember now runs locally. In FAVA Trails' 49-case benchmark, an Unsloth quantized Qwen 3.6 model proved on par with Google Gemini, and every mistake it made was a recoverable rejection rather than a quiet approval of weak material.

https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=substack&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=note
```

## r/LocalLLaMA

Check https://www.reddit.com/r/LocalLLaMA/about/rules/ immediately before posting. If a benchmark post with a maintainer disclosure and links would violate the current rules, skip it. Do not remove the disclosure or disguise the links.

### Primary title

```text
I tested quantized Qwen3.6 27B as a local gate for agent memory across 49 historical cases: every error was an extra rejection, and none reversed a historical rejection
```

### Primary body

```markdown
Disclosure: I maintain FAVA Trails, the open-source project I tested here.

FAVA Trails stores agent memory as versioned Markdown in Git. Draft thoughts pass a promotion gate before they become permanent memory, so the gate decides what future agents will recall. Version 0.6.0 lets that gate use a local model through an OpenAI-compatible endpoint, which keeps promotion candidates on the operator's machine and removes hosted inference from the critical path.

The gate looked like a good fit for a local model on paper, since the task has a stable policy prompt, structured JSON output, auditable historical cases, and asymmetric failure costs. I wanted to know whether a quantized model actually holds up on it.

I ran `unsloth/Qwen3.6-27B-GGUF` through Unsloth Studio with the exact production promotion prompt, against 39 historical thoughts with prior Gemini verdicts (26 approvals, 13 rejections) plus 10 synthetic canaries. The Gemini verdicts were references from earlier operation, not a fresh rerun.

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

Raw agreement was 79.6%, which sounds merely adequate until you look at the direction of the errors. Every disagreement was an additional rejection by the local model, and it did not reverse any of the 13 historical rejections. That direction fits a promotion gate, because a false rejection leaves the thought in drafts where it can be revised and resubmitted, while a false approval quietly adds weak material to future agent context.

For the nine historical thoughts the local model rejected against Gemini's approval, I asked OpenAI Codex running GPT 5.6 to judge each one against the same prompt. It favored Gemini in six cases and the local model in three, where the local model had caught a transient handoff stored as a permanent review, an implementation artifact misclassified as a specification, and an imperative task instruction presented as durable knowledge. That review is an interpretive challenge to the old verdicts rather than independent ground truth, and a separate positive canary accounted for the tenth disagreement.

The result is limited to one model on one prompt and corpus, so it does not establish general parity with Gemini or frontier models. Inputs over 40,000 characters were the weak spot, dropping to 2/6 raw agreement with a 122.9-second median latency. The model was also confident when it was wrong, averaging 0.93 confidence on disagreements, so confidence alone is not a useful escalation trigger. The released integration is provider-neutral and fails closed if the endpoint is unavailable or returns malformed output.

Full write-up:
https://machinewisdom.substack.com/p/fava-trails-v060-the-model-that-decides?utm_source=reddit&utm_medium=social&utm_campaign=fava-trails-v0-6-0&utm_content=rlocalllama

Benchmark evidence and disagreement audit:
https://github.com/MachineWisdomAI/fava-trails/issues/85#issuecomment-5142775500
```

### Short title

```text
Local Qwen3.6 27B as an agent-memory gate: valid verdicts in all 49 cases, and no reversed rejections
```

### Short body

```markdown
Disclosure: I maintain FAVA Trails, the open-source project I tested here.

FAVA Trails v0.6.0 can use a local OpenAI-compatible model to review drafts before they enter permanent agent memory. I tested `unsloth/Qwen3.6-27B-GGUF` through Unsloth Studio with the exact production prompt, against 39 historical thoughts with prior Gemini verdicts and 10 synthetic canaries. The Gemini verdicts were historical references, not a fresh rerun.

| Measure | Result |
|---|---:|
| Valid verdicts | 49/49 |
| Raw agreement | 39/49 |
| Historical rejections matched | 13/13 |
| Historical approvals matched | 17/26 |
| Canaries matched | 9/10 |
| Repeat consistency | 8/8 cases stable across three runs |

Every disagreement was an additional rejection, and the model never reversed a historical rejection. That error direction fits this gate, because a false rejection stays recoverable as a draft while a false approval quietly pollutes permanent memory. A second-model review by OpenAI Codex running GPT 5.6 examined the nine historical disagreements and favored Gemini in six cases and the local model in three.

The result is limited to one model on one prompt and corpus. Inputs over 40,000 characters dropped to 2/6 raw agreement with a 122.9-second median latency, and confidence did not identify bad verdicts.

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
