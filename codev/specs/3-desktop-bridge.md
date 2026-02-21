# Spec 3: Desktop Bridge

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 2 (Desktop Bridge section)
**Prerequisites:** Spec 2 (Trust Gate)

---

## Problem Statement

Claude Desktop on Windows cannot connect to the FAVA Trail MCP server running under WSL2. The MCP stdio transport requires a native executable path in `claude_desktop_config.json`, but `uv` and the Python environment live inside WSL2.

## Proposed Solution

A `wsl.exe` wrapper script (`scripts/mcp-fava-wrapper.sh`) that Claude Desktop invokes as its MCP command. The script routes stdio MCP traffic from native Windows into the WSL2 `fava-trail-server` process.

### Wrapper Script

```bash
#!/bin/bash
# scripts/mcp-fava-wrapper.sh
# Claude Desktop on Windows invokes this via wsl.exe
exec uv run --directory /home/younes/git/MachineWisdomAI/fava-trail fava-trail-server
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "fava-trail": {
      "type": "stdio",
      "command": "wsl.exe",
      "args": ["bash", "-lc", "/home/younes/git/MachineWisdomAI/fava-trail/scripts/mcp-fava-wrapper.sh"],
      "env": {
        "FAVA_TRAIL_DATA_REPO": "/home/younes/git/MachineWisdomAI/fava-trail-data"
      }
    }
  }
}
```

## Done Criteria

- Claude Desktop `claude_desktop_config.json` invokes wrapper script via `wsl.exe`
- MCP tool calls from Desktop reach the WSL2 server and return responses
- `save_thought` from Desktop creates thought in same trail as Code
- Cross-agent handoff: Code saves thought → Desktop reads it via `recall`

## Out of Scope

- Pull Daemon (Phase 4)
- Non-WSL2 environments (native Linux, macOS)
