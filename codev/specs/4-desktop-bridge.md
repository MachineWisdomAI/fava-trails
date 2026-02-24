# Spec 4: Desktop Bridge

**Status:** not started
**Epic:** 0002a-desktop-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (Desktop Bridge section)
**Prerequisites:** Spec 3 (Trust Gate)

---

## Problem Statement

Claude Desktop on Windows cannot connect to the FAVA Trail MCP server running under WSL2. The MCP stdio transport requires a native executable path in `claude_desktop_config.json`, but `uv` and the Python environment live inside WSL2.

## Proposed Solution

A `wsl.exe` wrapper script (`scripts/mcp-fava-wrapper.sh`) that Claude Desktop invokes as its MCP command. The script routes stdio MCP traffic from native Windows into the WSL2 `fava-trails-server` process.

### Wrapper Script

```bash
#!/bin/bash
# scripts/mcp-fava-wrapper.sh
# Claude Desktop on Windows invokes this via wsl.exe
exec uv run --directory /home/younes/git/MachineWisdomAI/fava-trails fava-trails-server
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "fava-trails": {
      "type": "stdio",
      "command": "wsl.exe",
      "args": ["bash", "-lc", "/home/younes/git/MachineWisdomAI/fava-trails/scripts/mcp-fava-wrapper.sh"],
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/home/younes/git/MachineWisdomAI/fava-trails-data"
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

- Pull Daemon (Phase 5)
- Non-WSL2 environments (native Linux, macOS)
