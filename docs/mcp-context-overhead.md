# MCP context overhead

This note records how FAVA Trails measures advertised MCP session-init text, what a
compact surface changes, and which learning-workflow steps the server actually
enforces. Figures below are for one serialization and one tokenizer. They are not
a universal client token cost.

## How to measure

```bash
fava-trails measure-mcp-context --surface both
```

The command serializes:

- initialize `instructions`
- `tools/list` items as this server advertises them (JSON, compact separators)

It records tokenizer name, MCP SDK version, enabled tool names, `lazy_loading`
(always `false`: every tool is listed at `tools/list`), and whether the cost
recurs. Instructions are sent once per `initialize`. `tools/list` is sent once
per list request; typical clients list once per session and only re-pay the cost
if they refresh the catalog.

Default tokenizer: `chars/4 heuristic` (`ceil(character_count / 4)`). If
`tiktoken` is installed, `cl100k_base` is recorded as an optional extra. Neither
figure is a client invoice.

## Recorded baseline

Measured 2026-09-11 in this repository against MCP SDK 2.2.0, all 17 tools
enabled, no lazy loading, tokenizer `chars/4 heuristic`, no `tiktoken`.

| Surface | Instructions tokens | tools/list tokens | Session-init tokens | Session-init chars |
| --- | ---: | ---: | ---: | ---: |
| full (default) | 961 | 5451 | 6412 | 25647 |
| compact | 161 | 3166 | 3327 | 13303 |

`get_usage_guide` body (on demand, not in session-init): 2520 heuristic tokens
(10077 chars). An evaluator previously estimated about 6000 tokens of schemas and
instructions versus about 1600 for a committed agent guide; that estimate was
client-specific and is not reproduced here as a universal number.

Budget, from the full session-init baseline: compact session-init tokens must be
≤ 70% of full under the same tokenizer. This run: 3327 / 6412 ≈ 0.52. Met.

Largest full-surface source is advertised `tools/list` JSON (schemas, then
descriptions), then initialize instructions. Compact therefore:

1. Shortens initialize instructions and points at `get_usage_guide`.
2. Shortens tool descriptions (drops duplicated session/promotion prose).
3. Omits advertised `outputSchema` on `tools/list`. Server-side validation still
   uses `TOOL_DEFINITIONS`.

Input schemas, tool names, and authorization are unchanged.

## Compact surface

Default remains `full` (backward compatible). Opt in per MCP process:

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "fava-trails-server",
      "env": {
        "FAVA_TRAILS_MCP_SURFACE": "compact"
      }
    }
  }
}
```

Unknown values log as `full` at server start so a typo does not fail the process.
`fava-trails measure-mcp-context` rejects unknown surfaces.

## recall / save / promote comparison

Same task on both surfaces (catalog inspection plus shared handlers):

| Check | full | compact |
| --- | --- | --- |
| Token usage (session-init, this tokenizer) | 6412 | 3327 |
| Discoverability of recall, save_thought, propose_truth, get_usage_guide, list_scopes | yes | yes |
| All 17 tools advertised | yes | yes |
| Input schemas | full | same |
| Advertised outputSchema | yes | omitted |
| Session-start recall trio in initialize/tool text | yes | no; in `get_usage_guide` |
| Promotion “mandatory” prose on propose_truth/save_thought | yes | no; in `get_usage_guide` |
| Error recovery (missing scope hint, conflict block, schema errors) | same handlers | same handlers |

Skipped-step risk on compact: if the client never calls `get_usage_guide` and
does not inject its own guide, it may skip session-start `recall` or
`propose_truth` after `save_thought`. The server does not invoke those steps on
either surface.

## What the server enforces vs prompt/client behavior

Server-enforced (same on both surfaces):

- `FAVA_TRAILS_AGENT_ID` identity match; caller `agent_id` cannot impersonate
- governed / authoring / history visibility
- operator-only tools (`diff`, `conflicts`, `rollback`, `forget`, `learn_preference`)
- writes require a configured agent identity
- input and output validation against `TOOL_DEFINITIONS`
- unpromoted drafts are not governed current records

Prompt/client behavior (not enforced by listing or instructions):

- calling `get_usage_guide`
- session-start recall of status/decisions/gotchas
- deciding work is “finalized” and calling `propose_truth`
- writing `FAVA_TRAILS_SCOPE` into `.env`
- whether the client shows initialize instructions or re-lists tools

Instructions do not provide reliable cross-session sharing. Sharing requires
`propose_truth` plus durable approval. Asking an agent to remember something in
the MCP instructions field does not make it available to the next session.
