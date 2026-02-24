## Phase 3 Review — Rebuttal

### Issues: Product name headings/body text + scope examples + pytest command — ALL FIXED

All four issues identified by reviewers were valid and have been applied:

1. **"FAVA Trail" → "FAVA Trails" in headings** — README.md, AGENTS.md, AGENTS_SETUP_INSTRUCTIONS.md, AGENTS_USAGE_INSTRUCTIONS.md, CLAUDE.md h1 headers and intro paragraphs updated.

2. **AGENTS.md body scope examples** — Two occurrences of `mw/eng/fava-trails` in body text updated to `mw/eng/fava-trails`.

3. **AGENTS.md pytest command** — `--cov=fava_trails` → `--cov=fava_trails` (functional fix — fava_trails module no longer exists).

4. **README.md Engine label** — Already fixed during Phase 3 iter 1 before consultation.

### Intentionally Preserved (All Reviewers Confirmed)
- `fava-trails-data` — data repo stays unchanged per architect directive
- `~/.fava-trails` — default home dir
- `.fava-trails.yaml` — config filename (singular "trail" for the config file is correct)
- `FAVA_TRAILS_SCOPE`, `FAVA_TRAILS_SCOPE_HINT` — intentionally singular per architect review comment on spec

All 128 tests pass. Spec 12 all three phases complete.
