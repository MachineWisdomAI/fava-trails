# Review TICK 1b-001: Recall Query Word-Level Matching + Scope Test Coverage

**Status:** completed
**Spec:** `codev/specs/1b-storage-substrate-amendments.md` (Amendments section)
**Change type:** Bug fix (2 lines) + test coverage (4 new tests)
**Tests:** 69 → 73

---

## What Was Done

Investigation of `recall()` returning 0 results during cross-agent handoff (Claude Desktop → Claude Code).

**Root cause:** `trail.py:333` used exact substring matching (`if query_lower not in searchable`). When both `query` and `scope` parameters were specified, the scope filter correctly identified matching thoughts, but the query filter rejected them because multi-word query strings weren't contiguous substrings in the searchable text.

Example: `recall(query="onboarding start-here", scope={"tags": ["start-here"]})` — the scope filter matched (thought has tag `"start-here"`), but the query filter rejected because the searchable text contained `"onboarding handoff start-here"` and `"onboarding start-here"` isn't a contiguous substring.

**Misdiagnosis path:** Initial hypothesis was a tag scope filter bug. The Claude Desktop handoff agent concluded it was a stale MCP server session. Neither was correct. The actual bug was the query substring matching, confirmed by tracing exact recall calls against the code path.

## Commits

| Commit | Description |
|--------|-------------|
| `0f919c9` | Place SPIR v2 at `codev/spir-v2.md` |
| `aeebd8e` | Fix: recall word-level AND matching |
| `2afb276` | Test: 4 new recall tests |

## Spec Compliance

| Criterion | Status |
|-----------|--------|
| Multi-word recall query finds thoughts with words anywhere in searchable text | Pass |
| Single-word queries still work (backward compat) | Pass |
| `recall(scope={"tags": [...]})` returns matching thoughts | Pass (was working, now tested) |
| `recall(scope={"branch": "..."})` returns matching thoughts | Pass (was working, now tested) |
| Multi-tag scope uses subset match | Pass |
| Combined project + branch scope works | Pass |
| Tag-only search via query (tag not in content body) | Pass |
| Non-matching queries return empty | Pass |

## Lessons Learned

1. **Trace actual tool calls against code, not hypotheses** — both initial hypotheses (tag filter bug, stale server) were wrong. Mapping exact `recall()` calls to the code path (`trail.py:311-334`) revealed the substring matching was the issue.
2. **Test all scope dimensions** — `test_recall_by_scope` covered `project` but not `tags` or `branch`. When a filter has N dimensions, test all N.
3. **Multi-word queries need word-level matching** — exact substring matching is too fragile for agent-generated queries that naturally contain multiple search terms.
