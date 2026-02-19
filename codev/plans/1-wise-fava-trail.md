# Plan 1: Core MCP Server + JJ Backend

**Status:** integrated
**Spec:** `codev/specs/1-wise-fava-trail.md`

---

## Phase 1.1: Project Scaffold + Pydantic Models

**Files created:**
```
fava-trail/
├── pyproject.toml          # uv project: mcp, pydantic, pyyaml, python-ulid
├── scripts/install-jj.sh   # Download JJ pre-built binary
└── src/fava_trail/
    ├── __init__.py
    ├── models.py            # ThoughtFrontmatter, ThoughtRecord, SourceType, etc.
    └── config.py            # env vars + config.yaml loading
```

**Done criteria:**
- Pydantic models serialize/deserialize thought frontmatter
- YAML frontmatter round-trips correctly
- NAMESPACE_ROUTES dict maps all SourceType values

## Phase 1.2: VCS Backend + JJ Integration

**Files created:**
```
src/fava_trail/vcs/
├── __init__.py
├── base.py                  # VcsBackend ABC
└── jj_backend.py            # JjBackend(VcsBackend)
```

**Key patterns:**
- VcsBackend ABC: `init_trail()`, `new_change()`, `commit_files()`, `log()`, `diff()`, `abandon()`, `op_log()`, `op_restore()`, `conflicts()`, `gc()`
- JjBackend: subprocess calls to `jj` with `--color=never`
- Colocated mode: `jj git init --colocate`
- Semantic translation layer: all output parsed from `jj log --template` into structured data
- JJ 0.28.0 compatibility: `-n` not `-l`, `jj status` not `jj st`, `.format()` not `format_timestamp()`

**Done criteria:**
- JJ backend can init trail, create changes, commit files, read log
- All output is structured (no raw stdout returned)

## Phase 1.3: TrailManager + Tool Handlers

**Files created:**
```
src/fava_trail/
├── trail.py                 # TrailManager: VCS + models + per-trail mutex
└── tools/
    ├── __init__.py
    ├── thought.py           # start_thought, save_thought, get_thought, forget, supersede
    ├── recall.py            # recall (search + filtering)
    └── navigation.py        # diff, list_trails, conflicts
```

**Key patterns:**
- TrailManager: per-trail `asyncio.Lock`, namespace directory creation on `init()`
- `save_thought`: defaults to `drafts/` namespace
- `supersede`: atomic — new thought + backlink in single `commit_files()` call
- `recall`: hides superseded by default, filters by namespace/scope/query
- Decision without `intent_ref` logs a warning
- Automated GC via `_maybe_gc()` on writes

**Done criteria:**
- All 9 Phase 1 tool handlers work correctly
- Supersede is atomic (both files in single JJ change)
- Recall filtering works for namespace, scope, supersession

## Phase 1.4: MCP Server Entry Point

**Files created:**
```
src/fava_trail/server.py     # MCP server (stdio transport)
```

**Key patterns:**
- Clone pal-mcp-server pattern: `Server`, `stdio_server`, `@server.list_tools()`, `@server.call_tool()`
- Tool routing via handler dict
- Conflict interception layer: write ops check for conflicts before proceeding
- Error handling: all exceptions caught and returned as structured JSON
- Entry point: `fava-trail-server` CLI command in pyproject.toml

**Done criteria:**
- `uv run fava-trail-server` starts and responds to MCP
- `list_tools` returns 9 Phase 1 tools
- All tool calls route to correct handlers

## Phase 1.5: Test Suite

**Files created:**
```
tests/
├── conftest.py              # Fixtures: tmp trail repos, jj binary check
├── test_models.py           # 7 tests: frontmatter, serialization, round-trip
├── test_jj_backend.py       # 11 tests: init, commit, log, diff, abandon, conflicts, gc
└── test_tools.py            # 12 tests: save, get, recall, supersede, forget
```

**Done criteria:**
- 30/30 tests pass
- Integration tests use real JJ (not mocked)
- Supersede atomicity verified

## Phase 1.6: Code Review + Bug Fixes

**Review:** GPT-5.1 Codex code review via `mcp__pal__codereview`

**8 issues found and fixed:**
1. `jj log -l` → `-n` (JJ 0.28.0 CLI)
2. `jj st` → `jj status` (no alias)
3. `format_timestamp()` → `.format()` (JJ template syntax)
4. Removed unused `import json` in jj_backend.py
5. Conflict check on every tool call → restricted to write operations only
6. Template string fixes for JJ log format
7. Missing `--color=never` on some JJ commands
8. Minor error message improvements

**Done criteria:**
- All 30 tests still pass after fixes
- No JJ 0.28.0 CLI compatibility issues remain

## Implementation Notes

- Phase 2 tool handlers (`propose_truth`, `sync`, `rollback`, `learn_preference`) are pre-written in the codebase but NOT registered in `TOOL_DEFINITIONS` for Phase 1
- The handler code lives in `tools/thought.py` and `tools/navigation.py`
- Phase 2 will add these tools to `TOOL_DEFINITIONS` and write tests

**Note:** Current `server.py` registers 13 tools including Phase 2 tools. This should be restricted to 9 for Phase 1 compliance. Tracked as a Phase 2 cleanup item.
