# Spec 1b: Mutable Content Architecture

**Status:** draft
**Author:** Claude (SPIR with 3-way consensus)
**Amends:** Spec 1 (`1-wise-fava-trail.md`)
**Consensus:** GPT 5.2 (8/10 FOR), Gemini 3 Pro (9/10 AGAINST), Grok (8/10 NEUTRAL) — Unanimous support
**Consensus Continuation ID:** `437211f0-0754-4002-b29a-25f42b63bdb9`

---

## Problem Statement

The current FAVA Trail architecture treats every thought as an immutable file. To "update" a thought, you create a new file via `supersede`. This means:

1. **`jj diff` only ever shows new files added** — no content diffs, no evolution visible
2. **`jj log` shows a sequence of file creations** — no revision history for individual ideas
3. **Conflicts are impossible** — no two agents ever write to the same file path
4. **The conflict interception layer has nothing to intercept** — JJ's core value proposition (first-class algebraic conflicts) is completely unused

You could replace JJ with `mkdir` + `cp` + a timestamp and get the same behavior. That's a problem when the entire architectural thesis is "JJ's VCS primitives are the right foundation for agent memory."

### Quantifying the Waste

With the current design, refining one idea over 5 iterations produces:
- 5 `.md` files (4 superseded + 1 current)
- 5 file-creation commits in JJ
- 0 content diffs
- 0 meaningful entries in `jj diff`
- 0 conflicts, ever

With the proposed design, the same refinement produces:
- 1 `.md` file
- 5 commits showing content evolution
- Real diffs visible in `jj diff` and `jj log`
- Potential conflicts when two agents refine the same thought — exactly the "cognitive dissonance" the PRD envisions

## Proposed Solution

Split mutability rules into three layers based on the nature of each field:

### Layer 1: Identity Fields (Immutable)

These fields are the thought's birth certificate. They never change after creation.

| Field | Rationale |
|-------|-----------|
| `thought_id` | Stable identity for references |
| `parent_id` | Lineage must never change |
| `agent_id` | Provenance — who created this |
| `source_type` | Classification is set at birth |
| `created_at` | Timestamp is historical fact |
| `relationships` | Graph edges are append-only (add new, never delete) |
| `confidence` | Initial assessment is historical fact |
| `schema_version` | Format identifier |

### Layer 2: Lifecycle Fields (System-Mutable)

These fields are modified only by specific tools during lifecycle transitions. They are NOT freely editable by agents.

| Field | Modified By | Transitions |
|-------|------------|-------------|
| `validation_status` | `propose_truth`, Trust Gate | draft → proposed → approved/rejected |
| `superseded_by` | `supersede` | null → ULID (one-time, irreversible) |

### Layer 3: Content (Mutable)

The markdown body after the YAML frontmatter is freely editable by agents. JJ tracks every state. Diffs show evolution.

**Guard rail (status-based, not directory-based):** Content mutability is controlled by `validation_status`, not by which directory the file lives in. Content is mutable when `validation_status` is `DRAFT` or `PROPOSED`. Content freezes when:
- `validation_status` is `APPROVED`, `REJECTED`, or `TOMBSTONED`
- `superseded_by` is set (even if status is still DRAFT/PROPOSED)

To update frozen content, you must `supersede` it, which creates the explicit lineage that the audit trail requires.

## What This Enables

### 1. Meaningful Diffs

An agent saves a draft thought about a codev upgrade rationale. It refines the reasoning over three edits. `jj diff` now shows actual content evolution — what was added, what was reworded, what was removed. This is the "temporal recall" the Memcurial PRD envisions.

### 2. Real Conflicts

Two agents both edit the same thought — one adds a caveat, the other adds a code example. JJ produces an algebraic conflict. The conflict interception layer now has actual work: surface both versions to the agent, ask which to keep or how to merge. This is "cognitive dissonance" made concrete.

### 3. Fewer Files, Richer History

Instead of a chain of 5 superseded files for iterative refinement of one idea, you get 1 file with 5 JJ commits showing its evolution. Supersession is reserved for what it should mean: "this thought is conceptually wrong, here's the replacement" — not "I want to add a sentence."

### 4. Diffs as Signal for the Knowledge Graph

When Phase 3 builds the `thought_relationships` table, content diffs become a signal source. A thought that was edited 8 times is probably more important than one that was written once and never touched. A thought that had a conflict resolved is capturing a genuine disagreement between agents. These are exactly the signals that the Temporal Knowledge Graph needs.

## Design Changes

### New `update_thought` Tool (Consensus Decision)

All three models recommended a **separate `update_thought` tool** rather than overloading `save_thought`. Rationale: LLMs may hallucinate thought IDs, and a separate tool reduces accidental overwrites. `save_thought` remains "create only."

**`update_thought` parameters:**
- `thought_id` (required): ULID of the thought to update
- `content` (required): New markdown body content
- `trail_name` (optional): Trail to use

**Validation:**
- Thought must exist (fail hard if not found — never create with a supplied ID)
- `validation_status` must be `DRAFT` or `PROPOSED` (status-based check)
- `superseded_by` must be null (content frozen if already superseded)
- Only content (markdown body) is modified — frontmatter is loaded from existing file and re-serialized verbatim (tamper-proofing)
- JJ commit message: `"Update thought {id[:8]} [{source_type}] in {namespace}/"`

**`save_thought` is unchanged** — always creates a new thought with a new ULID. No `thought_id` parameter.

### `_find_thought_path` Utility (Consensus Refinement)

Extract the "find thought file path by ULID" logic into a reusable private method on `TrailManager`. Currently duplicated in `supersede` (`trail.py:169-175`) and `get_thought` (`trail.py:141-146`). The new `update_thought` method also needs it.

```python
def _find_thought_path(self, thought_id: str) -> Optional[Path]:
    """Find the file path for a thought by its ULID. Searches all namespaces."""
    for p in self.trail_path.glob("thoughts/**/*.md"):
        if p.stem == thought_id:
            return p
    return None
```

### `_get_namespace_from_path` Utility (Consensus Bug Fix)

Fix namespace derivation for nested directories. Current code in `supersede` uses `original_path.parent.name` which returns `"firm"` for `thoughts/preferences/firm/`, losing the `preferences/` prefix.

```python
def _get_namespace_from_path(self, path: Path) -> str:
    """Get the namespace relative to thoughts/ directory."""
    thoughts_dir = self.trail_path / "thoughts"
    return str(path.parent.relative_to(thoughts_dir))
```

### `supersede` Role Narrows

`supersede` is no longer "the only way to update a thought." It becomes the tool for **conceptual replacement** — when the conclusion itself is wrong, not when the articulation needs improvement.

- **Edit-in-place** (via `update_thought`): Refining an idea. Same thought, better content.
- **Supersede**: Replacing a conclusion. New thought with `parent_id` pointing to the original. Clean break in thought lineage.

### `ValidationStatus` Expansion

Current: `DRAFT` | `PROPOSED` | `APPROVED` | `REJECTED`

Proposed: `DRAFT` | `PROPOSED` | `APPROVED` | `REJECTED` | `TOMBSTONED`

- `TOMBSTONED`: Content stripped (replaced with tombstone message), metadata preserved. Used when approved thoughts are superseded or when stale drafts are cleaned up. Full content recoverable from JJ/git history. **Not secure deletion** — for privacy-grade redaction, use `git filter-branch` or BFG.

### Stale Draft Handling

Drafts unpromoted for a configurable period (default: 30 days) are auto-promoted to `proposed` (Trust Gate decides their fate). This preserves good information that might otherwise be lost to procedural lousiness.

- Configurable per trail via `TrailConfig.stale_draft_days` (default: 30, 0 = disabled)
- Auto-promotion sets `metadata.extra.promotion_reason = "stale_timer"` — not a separate state, just metadata
- Trust Gate can still reject auto-promoted thoughts

### Content Freeze on Approval

When `propose_truth` promotes a thought to `approved`, or when the Trust Gate approves it, the content becomes immutable from that point forward. Any `update_thought` call targeting a frozen thought returns an error:

```json
{
  "status": "error",
  "message": "Thought {id} is content-frozen (status: approved). Use supersede to create a replacement."
}
```

Content is also frozen when `superseded_by` is set, even if the thought is still in DRAFT/PROPOSED status:

```json
{
  "status": "error",
  "message": "Thought {id} is content-frozen (already superseded by {superseded_by}). Edit the replacement thought instead."
}
```

### Conflict Interception Exception Path (Consensus Refinement)

The current conflict interception layer blocks ALL write operations when any conflict exists (`server.py:304-320`). This prevents the conflict resolution UX from working, since `update_thought` needs to write to resolve a conflict.

**Change:** When conflicts exist, `update_thought` is permitted if and only if the target `thought_id` matches one of the conflicted files. All other write operations remain blocked.

### Conflict Resolution UX

With mutable content, real conflicts will occur. The conflict interception layer provides actionable resolution:

**Current:** Blocks all write operations when any conflict exists. Resolution hint says "use supersede."

**Proposed:** When a conflict is detected on a specific thought file:
1. Extract both sides of the conflict from JJ (parse conflict markers from working copy)
2. Return structured payload with: base content, side A content, side B content
3. Agent resolves by calling `update_thought` with `thought_id` and merged content
4. JJ records the resolution as a normal commit
5. If conflict markers are unparseable, fall back to: `"Manual intervention required. Use rollback to restore pre-conflict state."`

The `conflicts` tool response gains richer structure:
```json
{
  "status": "conflict",
  "conflicts": [
    {
      "thought_id": "01JMKR3V...",
      "file_path": "thoughts/drafts/01JMKR3V....md",
      "description": "Two agents edited this thought concurrently",
      "side_a": "Content from agent claude-code...",
      "side_b": "Content from agent claude-desktop...",
      "base": "Original content before divergence..."
    }
  ]
}
```

### Bug Fix: `propose_truth()` Persist (Included)

`trail.py:304-307` — when a thought already exists outside drafts, `propose_truth()` mutates `validation_status` in memory but does NOT write to disk or commit via JJ. Fix: write the updated record to disk and commit.

## Files Affected

| File | Change |
|------|--------|
| `src/fava_trail/models.py` | Add `TOMBSTONED` to `ValidationStatus`. Add `stale_draft_days` to `TrailConfig`. |
| `src/fava_trail/trail.py` | Add `update_thought()`, `_find_thought_path()`, `_get_namespace_from_path()`. Add content-freeze guard. Fix `propose_truth()` persist bug. Refactor `supersede` and `get_thought` to use new utilities. |
| `src/fava_trail/server.py` | Register new `update_thought` tool. Update `supersede` tool description to emphasize "conceptual replacement." |
| `src/fava_trail/tools/thought.py` | Add `handle_update_thought()`. Update `_serialize_thought` for `TOMBSTONED` status. |
| `src/fava_trail/tools/navigation.py` | Enhance `handle_conflicts()` to return content sides. |
| `src/fava_trail/vcs/jj_backend.py` | Enhance `conflicts()` to extract file content from conflict markers. Add `get_conflict_content()` method. |
| `src/fava_trail/vcs/base.py` | Extend `VcsConflict` with `side_a`, `side_b`, `base` fields. |
| `tests/test_tools.py` | Tests for update_thought, content-freeze, conflict resolution flow. |
| `tests/test_models.py` | Tests for `TOMBSTONED` status. |
| `CLAUDE.md` | Update documentation: when to use update_thought (refine) vs. supersede (replace conclusion). |

## Success Criteria

1. `update_thought` updates existing thought content in-place (same file, same ULID)
2. `jj diff` shows actual content changes after `update_thought` (not just new file)
3. `jj log` shows revision history for a single thought file
4. `update_thought` on an `approved` thought returns content-freeze error
5. `update_thought` on a superseded thought returns content-freeze error
6. `update_thought` on a non-existent thought returns error
7. `update_thought` preserves all frontmatter identity fields (tamper-proof)
8. `save_thought` still always creates new thoughts (no regression)
9. `supersede` still works as before (creates new file, backlinks original)
10. `ValidationStatus.TOMBSTONED` is recognized by all tools
11. `conflicts` tool returns structured side_a/side_b/base content when available
12. Conflict interception allows `update_thought` for conflicted thought IDs
13. `propose_truth()` bug fixed — persists `validation_status` change to disk and commits
14. Namespace derivation works for nested dirs (preferences/client, preferences/firm)
15. All existing tests continue to pass (no regression)
16. New tests cover: update_thought, content-freeze guard, tombstoned status, conflict content extraction, namespace derivation, frontmatter tamper-proofing

## Consensus Summary

| Model | Stance | Score | Key Contribution |
|-------|--------|-------|-----------------|
| GPT 5.2 | FOR | 8/10 | Status-based mutability check, conflict interception exception path, namespace derivation bug, separate update_thought tool |
| Gemini 3 Pro | AGAINST | 9/10 | "Immutable file was anti-pattern for VCS-backed system." Freeze-on-approval is non-negotiable. Robust conflict parser with fallback. |
| Grok | NEUTRAL | 8/10 | Config flag for mutable states, end-to-end conflict testing, recovery hints in TOMBSTONED metadata |

## Out of Scope

- Remote sync architecture (orphan branches, bookmarks) — separate spec
- Stale draft auto-promotion daemon — Phase 2 implementation
- Trust Gate integration — Phase 3
- Semantic search over content diffs — Phase 3
