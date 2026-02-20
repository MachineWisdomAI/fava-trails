# Plan 0: Repository Separation — Engine vs. Data

**Status:** integrated
**Spec:** `codev/specs/0-repo-separation.md`

---

## Phase 0.1: Create OSS `fava-trail` repo

**Files created:**
```
/home/younes/git/MachineWisdomAI/fava-trail/
├── pyproject.toml           # moved from fava-trail-data
├── uv.lock                  # moved
├── scripts/install-jj.sh    # moved
├── src/fava_trail/          # moved (all Python source)
├── tests/                   # moved
├── codev/                   # moved (SPIR docs are the tool's history)
│   ├── specs/
│   ├── plans/
│   ├── reviews/
│   └── resources/
│       ├── prd-v2.md        # copied from Downloads
│       └── architectural-choices.md
├── CLAUDE.md                # rewritten for OSS context
├── LICENSE                  # Apache-2.0
└── .gitignore
```

**Done:** Git initialized, all source committed, `uv run pytest` passes.

## Phase 0.2: Enhance config.py for absolute paths

**File modified:** `src/fava_trail/config.py`

**Changes:**
- `get_trails_dir()`: check if `config.trails_dir` is absolute; if so, use directly
- New: `FAVA_TRAILS_DIR` env var override (highest priority for trails location)
- Tests: add `test_config.py` for path resolution

## Phase 0.3: Create internal `fava-trail-data` repo

**Files created:**
```
/home/younes/git/MachineWisdomAI/fava-trail-data/
├── config.yaml              # global FAVA Trail config for MachineWisdomAI
├── Makefile                 # setup target: install fava-trail, set env, init trail
├── CLAUDE.md                # company-specific agent instructions
├── .gitignore               # ignores trails/*/.jj, trails/*/.git, trails/*/thoughts/
└── trails/                  # empty initially; JJ repos created by server
```

**Done:** Git initialized, config committed.

## Phase 0.4: Wire together and verify

- Set `FAVA_TRAIL_DATA_REPO` to point to `fava-trail-data/`
- Run `fava-trail-server` from `fava-trail/` repo
- Verify all 13 tools respond
- Create a test trail, save a thought, recall it

## Phase 0.5: Commit and verify

- All 30 tests pass in `fava-trail/`
- Both repos have clean git history
- No Python source in `fava-trail-data/`
