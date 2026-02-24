# Spec 0: Repository Separation — Engine vs. Data

**Status:** integrated
**Author:** Claude (with 3-way consensus: GPT-5.1 Codex, Gemini 3 Pro, O3)
**Continuation ID:** `16cf1bcf-6d6c-41fc-98ee-3da62dd1a011`

---

## Problem Statement

FAVA Trail currently exists as a single directory (`fava-trails-data/`) containing both:
1. The **MCP server Python package** (generic, open-sourceable)
2. An implied **company data store** (MachineWisdomAI-specific trail data)

This conflation creates three problems:
- **IP leakage risk**: Open-sourcing the MCP server would expose company memory if they share a repo
- **Distribution friction**: Users who want the tool don't want our data, and vice versa
- **Architecture violation**: The PRD (Section 4.4) mandates that "agents interact with memories as semantic objects, never with VCS commands directly" — the tool and the data are fundamentally different concerns

## Proposed Solution

Split into two repositories following the **Engine vs. Fuel** pattern (3/3 model consensus, avg 8.3/10 confidence):

### Repo 1: `fava-trails` (Engine — Open Source)

The FAVA Trail MCP server as a pip-installable Python package.

- **Location:** `MachineWisdomAI/fava-trails` on GitHub (public)
- **License:** Apache-2.0
- **Distribution:** PyPI (`pip install fava-trails` / `uv add fava-trails`)
- **Contents:** All Python source (`src/fava_trails/`), tests, CI/CD, docs, LICENSE
- **Entry point:** `fava-trails-server` CLI command
- **SPIR docs:** `codev/` directory lives here (implementation history is part of the tool's story)
- **PRD + architectural choices:** `codev/resources/` (these inform the product, not the company data)

### Repo 2: `fava-trails-data` (Fuel — Internal)

MachineWisdomAI's versioned agentic memory — the actual trail data.

- **Location:** `MachineWisdomAI/fava-trails-data` on GitHub (private)
- **Contents:**
  - `config.yaml` — Global FAVA Trail configuration for MachineWisdomAI
  - `Makefile` — Bootstrap and operational commands
  - `trails/` — Directory containing JJ colocated repos (one per trail)
  - `CLAUDE.md` — Agent instructions specific to MachineWisdomAI's workflows
  - `.gitignore` — Ignores inner JJ repo artifacts (`.jj/` directories)
- **NOT a Python package** — no `src/`, no `pyproject.toml` with build system
- **Dependency:** Requires `fava-trails` to be installed (via pip/uv)

## Architecture

```
┌─────────────────────────────────────────┐
│  fava-trails (OSS, PyPI)                 │
│  ├── src/fava_trails/                    │
│  │   ├── server.py          (MCP)      │
│  │   ├── config.py          (discovery) │
│  │   ├── models.py          (Pydantic)  │
│  │   ├── trail.py           (manager)   │
│  │   ├── vcs/jj_backend.py  (JJ ops)   │
│  │   └── tools/*.py         (handlers)  │
│  ├── tests/                             │
│  └── codev/                 (SPIR docs) │
└──────────────┬──────────────────────────┘
               │ FAVA_TRAILS_DATA_REPO env var
               │ points to ↓
┌──────────────▼──────────────────────────┐
│  fava-trails-data (internal)             │
│  ├── config.yaml                        │
│  ├── Makefile                           │
│  ├── CLAUDE.md                          │
│  ├── .gitignore                         │
│  └── trails/                            │
│      ├── default/    (.jj/ + .git/)     │
│      ├── project-x/  (.jj/ + .git/)    │
│      └── ...                            │
└─────────────────────────────────────────┘
```

## Config Discovery

The `fava-trails` server discovers trail data via environment variable:

```
FAVA_TRAILS_DATA_REPO=/path/to/fava-trails-data
```

The server reads `$FAVA_TRAILS_DATA_REPO/config.yaml` and manages trails under `$FAVA_TRAILS_DATA_REPO/trails/`. This is already how `config.py` works — the only change needed is ensuring `trails_dir` in config supports absolute paths.

### Bootstrap Flow (internal repo)

```bash
# 1. Clone internal repo
git clone git@github.com:MachineWisdomAI/fava-trails-data.git

# 2. Install the MCP server
uv tool install fava-trails  # or: pip install fava-trails

# 3. Set FAVA_TRAILS_DATA_REPO (bootstrap does this)
make setup  # sets env var, creates initial trail if needed
```

## Nested VCS Handling

The internal repo is a regular Git repo. Each trail inside `trails/` is a JJ colocated repo (`.jj/` + `.git/`). The outer Git repo must `.gitignore` the inner repos' VCS directories to avoid conflicts:

```gitignore
# fava-trails-data/.gitignore

# Inner VCS repos (each trail has its own JJ+Git history)
trails/*/.jj/
trails/*/.git/

# Trail content (managed by JJ, not outer git)
trails/*/thoughts/

# Keep trail-specific config (tracked by outer git)
# trails/*/.fava-trails.yaml is NOT ignored — it's committed

# Python artifacts
__pycache__/
*.pyc
.venv/
```

**Important:** The outer Git repo tracks config and structure. Trail-specific config files (`trails/*/.fava-trails.yaml`) ARE tracked by the outer Git repo. The inner JJ repos track thought content. They are independent version histories.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Plugin system | Deferred to Phase 2+ | All 3 models suggested it; GPT-5.1 Codex says defer, Gemini says now, O3 says optional. We defer: YAGNI for MVP, but we'll design config.yaml to be extensible. |
| Internal repo as Python package | No | Pure data/config repo. No build system, no wheels. Simplest possible structure. |
| Naming | `fava-trails` (OSS) / `fava-trails-data` (internal) | Clear distinction. `fava-trails` is the generic product. `wise-` prefix is MachineWisdomAI's convention. |
| SPIR docs location | OSS repo (`fava-trails/codev/`) | Implementation docs are part of the tool's history, not the company data. Eventually FAVA Trail will store its own SPIR docs (self-hosting). |
| Config changes | Add `FAVA_TRAILS_DIR` override, support absolute `trails_dir` | Gemini and O3 both flagged `config.py` path resolution as too rigid. |

## Consensus Summary

| Model | Stance | Score | Key Point |
|-------|--------|-------|-----------|
| GPT-5.1 Codex | FOR pure separation | 8/10 | No plugins, pure data/config internal repo. Bootstrap via `make setup`. |
| Gemini 3 Pro | AGAINST (but supports split) | 9/10 | Wants plugin architecture now. Internal repo as "control plane" with pyproject.toml. |
| O3 | NEUTRAL | 8/10 | Confirms industry-standard pattern (PostgreSQL binary vs data dir). Optional entry-point plugins. |

**Resolution:** All 3 support the split. We take the conservative path (defer plugins) but structure config.yaml to be forward-compatible with future extensibility.

## Success Criteria

1. `fava-trails` repo has all Python source, tests pass (`pytest`), and is pip-installable
2. `fava-trails-data` repo has config.yaml + Makefile + CLAUDE.md + trails/ structure
3. `FAVA_TRAILS_DATA_REPO` env var correctly points server to internal repo
4. No company-specific data exists in the OSS repo
5. `make setup` in internal repo bootstraps a working FAVA Trail environment
6. All 30 existing tests pass against the restructured code

## Out of Scope

- PyPI publishing (Phase 2)
- CI/CD pipelines (Phase 2)
- Plugin/hook architecture (Phase 2+)
- Trust Gate implementation (Phase 2)
- Semantic search / SQLite-vec (Phase 3)
