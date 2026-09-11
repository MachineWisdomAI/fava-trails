# Obvious-secret preflight

A Trust Gate reject is a **promotion verdict**. It is not proof that candidate
content was never stored or sent. Drafts are written to the data repo (and JJ/Git
history) on `save_thought`. `propose_truth` then sends the thought body to the
configured reviewer model and may rewrite rejection metadata onto the same draft.

This preflight is a **bounded, local check** for a small set of high-confidence
credential shapes. The complete MCP request (tool name plus arguments) is
scanned at `_call_tool` before JSON Schema validation and at `handle_call_tool`
before the first logger call or any lookup/JJ operation. A second scan runs after hook mutation
and before normal write and promotion paths persist or transmit the candidate,
including nested caller-controlled metadata and relationships. After Trust Gate
review, the assembled record (including reviewer, reasoning, provider, and model
fields) is scanned again before any governance write. Nested walks that exceed
depth 32 fail closed; unscanned content is never treated as clean. It is not
complete DLP, does not rewrite history, and does not delete already-stored
records.

## Where candidate content goes

| Step | Stored? | Sent off-box? | Notes |
| --- | --- | --- | --- |
| Tool input (`content`, `reason`, metadata, relationships, identifiers, query/prefix, JJ args, tool name) | Process memory only until a write succeeds | No | Complete MCP name plus arguments are scanned before schema validation, log, or lookup; body logs record lengths only |
| Preflight reject on save / update / supersede / MCP arguments | No new thought file; no new JJ/Git snapshot of the candidate; no canary-bearing trail directory | No | Scans the tool name plus argument object before schema validation or log/lookup, then body plus nested caller-controlled strings after hooks; safe error names the pattern id only; block logs use a fixed message |
| `save_thought` success | Draft markdown under `thoughts/drafts/` plus a JJ commit | Only if `push_strategy=immediate` later publishes the repo | This is persistence, not review |
| `update_thought` / `supersede` success | In-place rewrite or a new draft successor in history | Same as save | Supersede `reason` and copied metadata/relationships are also scanned |
| `propose_truth` LLM review | Already on disk from the draft | **Yes** — thought body and redacted metadata (`project` / `branch` / `tags`) are in the reviewer user message | Assembled Trust Gate metadata is scanned before write-back; a supported pattern in reviewer/reasoning/provider/model blocks persist and leaves the draft unchanged |
| Promotion approve | Copy into the permanent namespace; original path removed | Already sent if LLM review ran | |
| Legacy draft that matches the preflight | **Left unchanged** | **Not** sent to the reviewer; **not** copied to a permanent namespace or a supersession successor | Prior persistence is not erased |
| Exports / Rich Views | Approved (and otherwise selected) records already on disk | Local generation | Preflight does not scrub historical files |
| MCP `content_preview` / `get_thought` | Reads existing files | Returned to the caller | Authoring visibility can still show a legacy secret draft |

## Supported patterns

The detector matches **shapes**, never a secret manager or entropy classifier:

- PEM private-key headers (`BEGIN … PRIVATE KEY`)
- AWS access key ids (`AKIA` + 16 uppercase alphanumerics)
- GitHub PATs (`ghp_…`, `github_pat_…`)
- OpenRouter keys (`sk-or-v1-` + 32+ alphanumerics)
- OpenAI-style keys (`sk-` / `sk-proj-` + 32+ alphanumerics)
- Stripe live keys (`sk_live_` / `rk_live_`)
- Slack tokens (`xoxb-` / `xoxp-` / similar)

Placeholders such as `sk-or-v1-...`, environment variable **names**, password-hashing
discussion, and ordinary architecture notes are intended to pass. Generic
`password:` strings, connection strings without these prefixes, and novel token
formats are **out of scope**.

Known false positives include well-formed documentation examples that use a real
token shape (for example AWS's `AKIAIOSFODNN7EXAMPLE`). Rewrite the example so it
does not match a supported pattern, or keep it out of thought bodies and metadata.

## Operator-facing errors

Failures raise `ObviousSecretError` with a pattern id and a fixed explanation.
They never interpolate the matched text into logs, exceptions, Trust Gate
reasoning, or MCP messages. Block logs use a fixed warning and omit pattern ids.
For a legacy draft the message also states that the existing file was left unchanged.

## Limits

- Not a substitute for vault storage, repo secret scanning, or provider-side key
  revocation.
- Does not claim coverage of all credentials, passwords, or PII.
- Does not garbage-collect drafts saved before this check, planted out of band,
  or published by an earlier `sync` / push.
- Nested caller-controlled structures are walked to depth 32. Exceeding that
  limit is a blocked finding (`nested_structure_too_deep`), not a clean miss.
  The error names the pattern id only and never echoes candidate content.
- Trust Gate LLM review remains a quality/safety **verdict after persist**, not a
  persistence or egress control. A secret that appears only in the review
  response is still refused before it is written to a new file or history.
