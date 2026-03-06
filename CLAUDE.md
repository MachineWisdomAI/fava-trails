# FAVA Trails Development

## Where to Work

- **Development**: `~/git/MachineWisdomAI/fava-trails/` (this repo)
- **NEVER modify**: `~/git/vendor/fava-trails/` (read-only, pinned at v0.4.12 for MCP)
- Vendor copy serves running MCP servers — modifying it risks breaking active tooling

## Worktree Conventions

- Feature branches use worktrees: `~/git/MachineWisdomAI/fava-trails-{slug}/`
- Never commit directly to `main` — always use a feature branch + PR
- Pre-flight check before starting work:
  ```bash
  git worktree list && git branch -r
  ```
- If another agent/branch is active on this repo, coordinate or use a separate worktree

## CI Requirements

PRs must pass:
- **test** — pytest suite (`uv sync --frozen && uv run pytest -v`)
- **Semantic PR title** — Conventional Commits format (e.g., `feat:`, `fix:`, `chore:`)

## Local Development

```bash
uv sync --frozen
uv run ruff check
uv run pytest -v
```

## Reference

- [AGENTS.md](AGENTS.md) — MCP tools, scope discovery, thought lifecycle
- [README.md](README.md) — Project documentation, architecture, configuration
