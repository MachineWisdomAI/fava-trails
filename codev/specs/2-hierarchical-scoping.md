# Spec 2: Hierarchical Scoping

**Status:** integrated
**Source:** Claude Desktop handoff spec + code analysis
**Prerequisites:** Spec 1b (storage substrate amendments) — integrated
**Supersedes:** Old Spec 9 (codev integration file watcher — dropped)

---

## Problem Statement

FAVA Trail's monorepo (Spec 1b) stores trails as directories under `trails/`. Currently all trails are flat siblings:

```
fava-trail-data/
└── trails/
    ├── default/           <- kitchen sink
    ├── wise-agents-toolkit/
    └── fava-trail/
```

There is no hierarchy. A company-wide coding convention and a throwaway debugging note live at the same level. Agents writing to `default` create a kitchen sink. Agents working on a specific epic see company-wide noise with no way to filter by scope distance.

The monorepo already supports nested directories — `trails/mw/eng/fava-trail/` is a valid path. We just aren't using it.

---

## Design

### `trail_name` Is a Path

A `trail_name` is a `/`-separated path under `trails/`. The server creates the directory structure on first write. No registry, no schema, no enforcement beyond filesystem validity.

```
trails/
├── mw/                              <- company-wide
│   ├── .fava-trail.yaml
│   └── thoughts/
│       ├── decisions/
│       │   └── 01JX...coding-standards.md
│       └── preferences/
│           └── firm/
│               └── 01JX...style-guide.md
├── mw/eng/                          <- engineering team
│   ├── .fava-trail.yaml
│   └── thoughts/
│       └── decisions/
│           └── 01JX...react-patterns.md
├── mw/eng/fava-trail/               <- project
│   ├── .fava-trail.yaml
│   └── thoughts/...
└── mw/eng/fava-trail/auth-epic/     <- task/epic
    ├── .fava-trail.yaml
    └── thoughts/...
```

Each scope has the same internal structure as a current trail: `.fava-trail.yaml` + `thoughts/{namespace}/`.

### Naming Convention (Recommended, Not Enforced)

```
{company}/{team}/{project}/{epic-or-task}
```

**Validation rules (enforced):**
- Lowercase alphanumeric + hyphens/dots/underscores per segment
- `/` separators
- No leading/trailing `/`, no empty segments
- No `..` or `\` (path traversal rejected)

**No depth limits.** No maximum, no minimum.

**Warning (not error):** If an agent writes to a single-segment trail (e.g., `trail_name="scratch"`), the server returns a warning in the response: `"Warning: trail 'scratch' is at root level under trails/. Consider using a scoped path like 'mw/scratch'."` This does NOT block the write.

### `trail_name` Is Required

`trail_name` is required on every tool call (except `list_scopes`). The server never reads `.env`, never walks directories, never has a default scope. The **agent** is responsible for knowing its scope.

If `trail_name` is missing, the server returns an error: `"trail_name is required. Pass your scope path (e.g. 'mw/eng/fava-trail')."` No default trail fallback.

### Reads: Explicit Multi-Scope with Globs

**No automatic cascade.** The agent decides which scopes to search. `recall` gains a `trail_names` parameter (plural) that accepts an array of scope paths, with glob support:

```python
recall(
    query="gotchas",
    trail_name="mw/eng/fava-trail/auth-epic",     # primary scope
    trail_names=[                                    # additional scopes to search
        "mw/eng/fava-trail",                         # project decisions
        "mw/eng",                                    # team standards
        "mw",                                        # company conventions
    ]
)
```

**With globs:**
```python
recall(
    query="React patterns",
    trail_name="mw/eng/fava-trail",
    trail_names=["mw/eng/*"]           # all projects under eng
)
```

**Glob semantics:**
- `*` matches one level: `mw/eng/*` matches `mw/eng/fava-trail`, `mw/eng/wise-agents-toolkit`, but NOT `mw/eng/fava-trail/auth-epic`
- `**` matches any depth: `mw/eng/**` matches everything under `mw/eng/` at any nesting level
- The server resolves globs by listing directories under `trails/`. Standard `Path.glob()`.
- Globs that resolve outside `trails/` are silently dropped (path containment check).
- `trail_name` (singular) is always included in the search. `trail_names` (plural) adds to it.

Results from all matched scopes are combined, deduplicated by `thought_id`, and each result includes `source_trail` indicating which scope it came from.

### Writes: To Your Scope Only

`save_thought` writes to the `trail_name` passed in the call. Period. No cascading writes.

### Cross-Scope Thought Elevation

`supersede` defaults to same scope (no behavior change). New optional parameter: `target_trail_name` — when provided, new thought lands in the target scope instead of the original's scope.

New MCP tool `change_scope` wraps `supersede` with cross-scope arguments:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | yes | ULID of the thought to elevate |
| `content` | string | yes | Content for the new scope (may be rewritten for broader audience) |
| `target_trail_name` | string | yes | Target scope path |
| `reason` | string | yes | Why this thought is being elevated |
| `trail_name` | string | yes | Source scope (where the original lives) |

Cross-scope supersede touches two trail directories. `commit_files` gains `allowed_prefixes` parameter to permit multi-prefix writes.

### `list_scopes`: Discover the Neighborhood

Renamed from `list_trails`. Recurses into nested directories. Finds all directories containing `thoughts/` at any depth.

```python
list_scopes(
    prefix="mw/eng",           # optional — filter by prefix
    include_stats=False         # optional — thought count + last write per scope
)
```

`list_trails` kept as alias for backward compatibility.

---

## Schema Changes

None. The scope is encoded in the `trail_name` — the directory path under `trails/`. No new frontmatter field. No schema version bump.

---

## Changes to Existing Tools

### `recall`

**New parameter:** `trail_names: Optional[list[str]]` — additional scopes to search. Supports glob patterns (`*`, `**`).

**Behavior:**
- `trail_name` (singular, existing) — the primary scope. Required.
- `trail_names` (plural, new) — additional scopes. Optional. Defaults to empty list.
- Results from all matched scopes are combined, deduplicated by `thought_id`.
- Each result includes `source_trail` indicating which scope it came from.

**Backward compatible:** Omitting `trail_names` works exactly as before.

### `supersede`

**New optional parameter:** `target_trail_name` — when provided, new thought lands in the target scope. Original stays in its scope, marked as superseded. Both changes in a single JJ change (atomic).

### `list_trails` → `list_scopes`

**Rename** with alias. Now:
- Recurses into nested directories
- Filters for dirs containing `thoughts/`
- Adds optional `prefix` filter
- Adds optional `include_stats`

### All Other Tools

`start_thought`, `get_thought`, `propose_truth`, `forget`, `sync`, `conflicts`, `rollback`, `diff`, `learn_preference`, `update_thought` — **unchanged**. They already accept `trail_name`. A nested trail name like `mw/eng/fava-trail` means the server resolves `trails/mw/eng/fava-trail/`. No logic change needed.

---

## Done Criteria

- [ ] `trail_name="mw/eng/fava-trail"` resolves to `trails/mw/eng/fava-trail/` (nested directories work)
- [ ] `save_thought(trail_name="mw/eng/fava-trail/auth-epic")` auto-creates scope directory on first write
- [ ] `recall(trail_name="X", trail_names=["Y", "Z"])` returns thoughts from all listed scopes
- [ ] `recall(trail_names=["mw/eng/*"])` resolves glob to one-level children of `mw/eng/`
- [ ] `recall(trail_names=["mw/eng/**"])` resolves glob to all scopes under `mw/eng/` at any depth
- [ ] Results include `source_trail` metadata indicating which scope each thought came from
- [ ] `supersede` across scopes works (source in one trail, target in another)
- [ ] `change_scope` tool wraps cross-scope supersede
- [ ] `commit_files` allows multi-prefix writes for cross-scope supersede
- [ ] `list_scopes()` discovers all nested scopes recursively
- [ ] `list_scopes(prefix="mw/eng")` filters by prefix
- [ ] Writing to root-level trail (e.g., `trail_name="scratch"`) returns warning in response
- [ ] Globs resolving outside `trails/` are silently dropped
- [ ] `trail_name` is required on all tool calls (no server-side default)
- [ ] Missing `trail_name` → error (no default fallback)
- [ ] Path traversal (`../etc/passwd`, `..`, `\`) → rejected
- [ ] All existing tests pass (no regressions)
- [ ] Tool count: 14 → 15 (add `change_scope`, rename `list_trails` → `list_scopes` with alias)

---

## Out of Scope

- Automatic cascade / backtracking (agents list scopes explicitly)
- Cross-scope contradiction resolution (agent's problem, not server's)
- Scope policies / access control / registry
- Scope rename / merge / alias tools
- Schema version bump (hierarchy is in directory structure, not frontmatter)
- Migration of existing data
- Max/min depth enforcement
- Server-side `.env` reading, walk-up resolution, or default scope
- Retrieval ranking by scope distance (all scopes in `trail_names` are treated equally)
