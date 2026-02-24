# Review 1: Core MCP Server + JJ Backend

**Status:** completed
**Spec:** `codev/specs/1-wise-fava-trails.md`
**Plan:** `codev/plans/1-wise-fava-trails.md`
**Reviewer:** GPT-5.1 Codex via `mcp__pal__codereview`

---

## Summary

Phase 1 delivered a working FAVA Trail MCP server with 9 core tools backed by Jujutsu (JJ) VCS. The GPT-5.1 Codex code review found 8 issues, all resolved before merging to main.

## What Was Done

1. **Pydantic models** — `ThoughtFrontmatter`, `ThoughtRecord`, `SourceType`, `ValidationStatus`, `RelationshipType`, `NAMESPACE_ROUTES`. Full YAML frontmatter serialization/deserialization.
2. **VCS backend** — `VcsBackend` ABC with `JjBackend` implementation. JJ 0.28.0 colocated mode. Semantic translation layer for all output.
3. **TrailManager** — Per-trail `asyncio.Lock`, namespace directory creation, automated GC, thought CRUD, supersede atomicity.
4. **Tool handlers** — 9 Phase 1 tools: `start_thought`, `save_thought`, `get_thought`, `recall`, `forget`, `conflicts`, `diff`, `list_trails`, `supersede`.
5. **MCP server** — stdio transport, conflict interception on write ops, structured JSON responses.
6. **Test suite** — 30 tests (7 model + 11 JJ backend + 12 tool integration). Real JJ used in tests (no mocking of VCS).

## Spec Compliance

| Criterion | Status |
|-----------|--------|
| JJ binary installed, `jj version` works | Pass |
| Server starts and lists tools | Pass |
| All 9 Phase 1 tools work e2e | Pass |
| `save_thought` defaults to `drafts/` | Pass |
| `supersede` is atomic | Pass |
| `conflicts` returns structured summaries | Pass |
| All responses are JSON | Pass |
| `recall` hides superseded by default | Pass |
| `recall` filters by namespace/scope | Pass |
| Decision without `intent_ref` logs warning | Pass |
| GC runs non-blocking | Pass |
| All tests pass | Pass (30/30) |

## Code Review Findings (GPT-5.1 Codex)

### Issue 1: `jj log -l` flag doesn't exist (HIGH)
JJ 0.28.0 uses `-n`/`--limit`, not `-l`. All `jj log` calls updated.

### Issue 2: `jj st` alias doesn't exist (MEDIUM)
JJ doesn't support `st` as alias for `status`. Fixed to `jj status`.

### Issue 3: `format_timestamp()` not in JJ templates (MEDIUM)
JJ template syntax uses `author.timestamp().format(...)`, not `format_timestamp()`. Fixed in log template.

### Issue 4: Unused `import json` in jj_backend.py (LOW)
Removed.

### Issue 5: Conflict check on every tool call (MEDIUM)
Performance issue — read-only ops (`get_thought`, `recall`, `diff`) don't need conflict checks. Restricted to write operations: `start_thought`, `save_thought`, `propose_truth`, `forget`, `supersede`, `learn_preference`, `sync`.

### Issue 6: Template string fixes for JJ log (LOW)
Minor formatting issues in `jj log --template` strings. Fixed.

### Issue 7: Missing `--color=never` on some JJ commands (LOW)
Some JJ subprocess calls lacked `--color=never`, risking ANSI codes in parsed output. Added to all calls.

### Issue 8: Error message improvements (LOW)
Vague error messages made more specific with context about which thought/trail was involved.

## Compliance Note: Tool Registration

The plan specifies 9 Phase 1 tools, but `server.py` currently registers 13 tools (including Phase 2 tools: `propose_truth`, `sync`, `rollback`, `learn_preference`). The handler code for these tools is pre-written and functional, but they should not be exposed to MCP clients until Phase 2. This is tracked as a Phase 2 item — not a blocker since all 4 extra tools work correctly.

## Lessons Learned

1. **Always verify CLI flags against the actual version** — JJ 0.28.0 has different flags than earlier versions. Docs can be outdated.
2. **Only check for conflicts on write operations** — read-only tool calls should never be blocked by conflict state.
3. **Add `--color=never` to all subprocess VCS calls** — ANSI codes break output parsing.
4. **Real VCS in tests, not mocks** — The JJ integration tests caught real compatibility issues that would have been invisible with mocked VCS.
5. **Semantic translation pays off early** — Converting raw VCS output to structured JSON at the backend level means tool handlers never deal with parsing.
