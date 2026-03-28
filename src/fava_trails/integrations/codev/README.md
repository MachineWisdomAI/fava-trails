# Codev Integration for FAVA Trails

Adds a codev-specific trust gate addendum that enforces quality checks on
specs, plans, and reviews stored as FAVA Trails thoughts.

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

## Setup

```bash
fava-trails integrate codev
```

This composes the generic trust gate prompt with the codev addendum and writes
the result to `trails/codev-artifacts/trust-gate-prompt.md` in your data repo.

### Flags

| Flag | Description |
|------|-------------|
| `--check` | Verify composed file matches current sources. Exit 1 on mismatch (CI-friendly). |
| `--diff` | Preview what would change without writing. |
| `--force` | Overwrite even if the composed file was manually edited. |

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

The composed prompt replaces the generic prompt for all `codev-artifacts/**`
scopes via the trust gate's hierarchical scope resolution.

## Artifact Type Detection

The trust gate reviewer detects artifact type from the scope path:
- `/specs/` in scope → specification checks
- `/plans/` in scope → plan checks
- `/reviews/` in scope → review checks

This requires `trail_name` in the redacted metadata (added in fava-trails v0.5.4+).
