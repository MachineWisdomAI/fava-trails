# Plan 3: Desktop Bridge

**Status:** not started
**Spec:** `codev/specs/3-desktop-bridge.md`

---

## Phase 3.1: Wrapper Script

**Files created:**
- `scripts/mcp-fava-wrapper.sh` — WSL2 wrapper for Claude Desktop stdio MCP

**Done criteria:**
- Script is executable (`chmod +x`)
- `wsl.exe bash -lc scripts/mcp-fava-wrapper.sh` starts the MCP server
- Stdio transport works (tool calls in, JSON responses out)

## Phase 3.2: Manual Verification

- Configure Claude Desktop with wrapper
- Run `list_trails` from Desktop
- `save_thought` from Desktop → `recall` from Code finds it
- `save_thought` from Code → `recall` from Desktop finds it

**Done criteria:**
- Cross-agent round-trip verified manually
- Both agents share the same monorepo trail data
