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

It records FAVA package version and git commit of the measured checkout
(candidate), the issue #104 tested release (`6c5278a40a86246014901a88417f3455a46cdfcc`),
tokenizer name, MCP Python SDK `mcp.Client` version, enabled tool names,
`lazy_loading` (always `false`: every tool is listed at `tools/list`), and whether
the cost recurs. Instructions are sent once per `initialize`. `tools/list` is sent
once per list request; typical clients list once per session and only re-pay the
cost if they refresh the catalog.

Default tokenizer: `chars/4 heuristic` (`ceil(character_count / 4)`). If
`tiktoken` is installed, `cl100k_base` is recorded as an optional extra. Neither
figure is a client invoice.

## Provenance

| Checkout | Role | FAVA version | Git commit | Client |
| --- | --- | --- | --- | --- |
| Issue #104 source review baseline | tested release | 0.6.1 | `6c5278a40a86246014901a88417f3455a46cdfcc` | `mcp.Client` 2.2.0 |
| This branch | candidate | 0.6.1 | current `git rev-parse HEAD` | `mcp.Client` 2.2.0 |

The tested release had no compact surface. Its full-surface payload was measured
with the same chars/4 serializer applied to that commit's advertised initialize
instructions and `tools/list` JSON.

## Recorded baseline

Tokenizer `chars/4 heuristic`, all 17 tools enabled, no lazy loading, no `tiktoken`.

Tested release (`6c5278a`, full surface only):

| Instructions tokens | tools/list tokens | Session-init tokens | Session-init chars | `get_usage_guide` chars / tokens |
| ---: | ---: | ---: | ---: | ---: |
| 961 | 5451 | 6412 | 25647 | 10077 / 2520 |

Candidate (this head, `mcp.Client` 2.2.0):

| Surface | Instructions tokens | tools/list tokens | Session-init tokens | Session-init chars |
| --- | ---: | ---: | ---: | ---: |
| full (default) | 1135 | 5793 | 6928 | 27708 |
| compact | 187 | 3179 | 3366 | 13458 |

`get_usage_guide` body on this candidate (on demand, not in session-init): 2871
heuristic tokens (11481 chars). An evaluator previously estimated about 6000 tokens
of schemas and instructions versus about 1600 for a committed agent guide; that
estimate was client-specific and is not reproduced here as a universal number.

Budget, from the candidate full session-init baseline: compact session-init tokens
must be ≤ 70% of full under the same tokenizer. This run: 3366 / 6928 ≈ 0.49. Met.

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

Executed on both surfaces via `handle_call_tool` (same handlers) with
`mcp.Client` 2.2.0 recorded as the client identity. Task: invalid save, missing
scope recall, `save_thought`, authoring `recall`, `propose_truth` (Trust Gate
review mocked). Results:

| Check | full | compact |
| --- | --- | --- |
| Token usage (session-init, this tokenizer) | 6928 | 3366 |
| Discoverability of recall, save_thought, propose_truth, get_usage_guide, list_scopes | yes | yes |
| All 17 tools advertised | yes | yes |
| Input schemas | full | same |
| Advertised outputSchema | yes | omitted |
| Executed save_thought | ok | ok |
| Executed authoring recall after save | count 1 | count 1 |
| Executed propose_truth | ok | ok |
| Error recovery: missing scope | status error | status error |
| Error recovery: save without content | failed | failed |
| Session-start recall trio in initialize text | yes | no; in `get_usage_guide` |
| Promotion “mandatory” prose in initialize text | yes | no; in `get_usage_guide` |

Skipped-step risk on compact: if the client never calls `get_usage_guide` and
does not inject its own guide, it may skip session-start `recall` or
`propose_truth` after `save_thought`. Full initialize text still includes those
prompts; the server does not invoke those steps on either surface.

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
- creating `.fava-trails.yaml` (do not write application `.env` files)
- whether the client shows initialize instructions or re-lists tools

Instructions do not provide reliable cross-session sharing. Sharing requires
`propose_truth` plus durable approval. Asking an agent to remember something in
the MCP instructions field does not make it available to the next session.
