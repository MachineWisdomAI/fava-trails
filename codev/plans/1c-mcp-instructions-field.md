# Plan 1c: MCP Server Instructions Field

**Spec:** `codev/specs/1c-mcp-instructions-field.md`
**Protocol:** TICK (amends Spec 1)

---

## Phase 1: Spec + Plan Artifacts

Create this plan and the spec. Commit.

**Done criteria:** Both files exist in `codev/specs/` and `codev/plans/`.

## Phase 2: Server `instructions` Field

**File:** `src/fava_trails/server.py`

### 2a: `_build_server_instructions()` function

New function near `_build_trail_name_desc()`. Returns condensed guidance string (~800-1000 tokens) covering scope discovery, session protocol, promotion mandate, agent identity, recalled-thought safety, and reference to `get_usage_guide`.

### 2b: `get_usage_guide` tool

New MCP tool. Reads `AGENTS_USAGE_INSTRUCTIONS.md` bundled as package data and returns its content. Add to `TOOL_DEFINITIONS` list and wire into `handle_call_tool` router.

### 2c: Wire into Server init

```python
server = Server("fava-trails", instructions=_build_server_instructions())
```

### 2d: Enhance 3 tool descriptions

- `recall`: Append Trust Gate warning
- `propose_truth`: Append mandatory promotion reminder
- `save_thought`: Append agent identity convention

### 2e: Bundle AGENTS_USAGE_INSTRUCTIONS.md as package data

Update `pyproject.toml` to include the file via hatch build config.

**Done criteria:** Server initializes with non-empty `instructions`; `get_usage_guide` returns file content; 3 tool descriptions enhanced.

## Phase 3: Update Documentation

- `AGENTS_USAGE_INSTRUCTIONS.md`: Add auto-injection note, mark SPIR section as optional
- `CLAUDE.md` (project): Note instructions field in Scope Discovery section
- `AGENTS.md`: Add note about auto-injected guidance

**Done criteria:** All three docs reference auto-injection.

## Phase 4: Tests + Review

- Test: `server` has non-empty `instructions`
- Test: `recall` description contains "WARNING"
- Test: `propose_truth` description contains "mandatory"
- Test: `save_thought` description contains "stable role"
- Test: `get_usage_guide` tool exists and returns content
- Run `uv run pytest -v` — all pass
- Create `codev/reviews/1c-mcp-instructions-field.md` with global CLAUDE.md maintainer deliverable

**Done criteria:** All tests pass; review doc complete.
