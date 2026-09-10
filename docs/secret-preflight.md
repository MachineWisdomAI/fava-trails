# Obvious-secret preflight

A Trust Gate reject is a **promotion verdict**. It is not proof that candidate
content was never stored or sent. Drafts are written to the data repo (and JJ/Git
history) on `save_thought`. `propose_truth` then sends the thought body to the
configured reviewer model and may rewrite rejection metadata onto the same draft.

This preflight is a **bounded, local check** for a small set of high-confidence
credential shapes. It runs before normal write and promotion paths persist or
transmit the candidate. It is not complete DLP, does not rewrite history, and
does not delete already-stored records.

## Where candidate content goes

| Step | Stored? | Sent off-box? | Notes |
| --- | --- | --- | --- |
| Tool input (`content`, `reason`) | Process memory only until a write succeeds | No | MCP argument logs record lengths, not bodies |
| Preflight reject on save / update / supersede | No new thought file; no new JJ/Git snapshot of the candidate | No | Safe error names the pattern id only |
| `save_thought` success | Draft markdown under `thoughts/drafts/` plus a JJ commit | Only if `push_strategy=immediate` later publishes the repo | This is persistence, not review |
| `update_thought` / `supersede` success | In-place rewrite or a new draft successor in history | Same as save | Supersede `reason` is also scanned |
| `propose_truth` LLM review | Already on disk from the draft | **Yes** — thought body is in the reviewer user message | Trust Gate reject metadata is written back onto the draft |
| Promotion approve | Copy into the permanent namespace; original path removed | Already sent if LLM review ran | |
| Legacy draft that matches the preflight | **Left unchanged** | **Not** sent to the reviewer; **not** copied to a permanent namespace | Prior persistence is not erased |
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
does not match a supported pattern, or keep it out of thought bodies.

## Operator-facing errors

Failures raise `ObviousSecretError` with a pattern id and a fixed explanation.
They never interpolate the matched text into logs, exceptions, Trust Gate
reasoning, or MCP messages. For a legacy draft the message also states that the
existing file was left unchanged.

## Limits

- Not a substitute for vault storage, repo secret scanning, or provider-side key
  revocation.
- Does not claim coverage of all credentials, passwords, or PII.
- Does not garbage-collect drafts saved before this check, planted out of band,
  or published by an earlier `sync` / push.
- Trust Gate LLM review remains a quality/safety **verdict after persist**, not a
  persistence or egress control.
