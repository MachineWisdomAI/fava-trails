# Codev Integration for FAVA Trails

Adds a codev-specific trust gate addendum that enforces quality checks on
specs, plans, and reviews stored as FAVA Trails thoughts, and configures
your codev project to use FAVA Trails as its artifact backend.

## Quick Start

Run from inside your codev project directory:

```bash
fava-trails integrate codev
```

This single command does two things:

1. **Composes the trust gate prompt** — merges the generic TG prompt with the
   codev addendum and writes it to `trails/codev-artifacts/trust-gate-prompt.md`
   in your data repo.
2. **Configures `.codev/config.json`** — auto-derives `<Org>/<Repo>` from your
   git remote and writes the `artifacts` section:
   ```json
   {
     "artifacts": {
       "backend": "cli",
       "command": "fava-trails",
       "scope": "codev-artifacts/<Org>/<Repo>"
     }
   }
   ```

Existing keys in `.codev/config.json` (shell, porch, terminal, etc.) are preserved.

## Scope Convention

Store codev artifacts under a hierarchical scope:

```
codev-artifacts/<Org>/<Repo>/specs/<N-name>/
codev-artifacts/<Org>/<Repo>/plans/<N-name>/
codev-artifacts/<Org>/<Repo>/reviews/<N-name>/
```

Example:
```
codev-artifacts/MachineWisdomAI/fava-trails/specs/26-codev-trust-gate-integration/
```

The trust gate prompt at `trails/codev-artifacts/trust-gate-prompt.md` governs
all scopes under `codev-artifacts/` via hierarchical resolution (first-match-wins).

## Flags

| Flag | Description |
|------|-------------|
| `--check` | Verify composed file matches current sources. Exit 1 on mismatch (CI-friendly). |
| `--diff` | Preview what would change without writing. |
| `--force` | Overwrite even if the composed file was manually edited or artifacts config differs. |
| `--scope <scope>` | Override auto-derived artifact scope (e.g., `--scope codev-artifacts/MyOrg/MyRepo`). |
| `--project-only` | Only configure `.codev/config.json`, skip TG prompt composition. |
| `--prompt-only` | Only compose TG prompt, skip project config. |

`--project-only` and `--prompt-only` are mutually exclusive.

### CI Staleness Check

Add to your CI pipeline:

```bash
fava-trails integrate codev --check
```

Returns exit code 1 if the composed prompt is stale (generic prompt or addendum
changed since last `integrate codev` run).

## How It Works

1. Reads the generic trust gate prompt from `trails/trust-gate-prompt.md`
2. Reads the codev addendum from the fava-trails package
3. Composes them with a provenance header (version, hash)
4. Writes to `trails/codev-artifacts/trust-gate-prompt.md`
5. If in a codev project, configures `.codev/config.json` with artifact settings

The composed prompt replaces the generic prompt for all `codev-artifacts/**`
scopes via the trust gate's hierarchical scope resolution.

## Artifact Type Detection

The trust gate reviewer detects artifact type from the scope path:
- `/specs/` in scope → specification checks
- `/plans/` in scope → plan checks
- `/reviews/` in scope → review checks

This requires `trail_name` in the redacted metadata (added in fava-trails v0.5.4+).
