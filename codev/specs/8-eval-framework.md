# Spec 8: Evaluation Framework

**Status:** not started
**Epic:** 0002a-desktop-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (eval sections)
**Prerequisites:** Spec 5 (Pull Daemon)

---

## Problem Statement

No automated tests exist for two critical operational properties:

1. **Crash recovery** — JJ's crash-proof snapshots should guarantee zero data loss after SIGKILL, but this is unverified
2. **Recall accuracy** — No metrics exist for recall precision/relevance against a known corpus

## Proposed Solution

Two evaluation scripts in `eval/`:

### `eval/crash_recovery.py`

SIGKILL chaos test against the MCP server with precise recovery verification.

**Test harness:** The script spawns the MCP server as a subprocess via `asyncio.create_subprocess_exec()` with stdio transport (stdin/stdout pipes). Communication uses JSON-RPC over stdio — the same protocol Claude Desktop uses. The harness sends `tools/call` JSON-RPC requests to `save_thought`, `recall`, etc.

**Test isolation:** Each test run creates a temporary `$FAVA_TRAILS_DATA_REPO` via `tempfile.mkdtemp()`, bootstraps it with `jj git init --colocate`, and sets `FAVA_TRAILS_DATA_REPO` in the subprocess env. Cleanup removes the temp dir after the test.

**Test sequence:**
1. Start MCP server subprocess with temp data repo
2. Save N thoughts via JSON-RPC `save_thought` calls, recording all returned `thought_id`s as the **pre-crash manifest**
3. Send `SIGKILL` to the server process mid-operation (after saving but potentially during a write)
4. Restart the server with the same temp data repo
5. Call `recall` for each thought in the pre-crash manifest
6. **Recovery oracle:** Every `thought_id` from the pre-crash manifest must be retrievable via `get_thought`. "Zero data loss" means: all thoughts that received a successful `save_thought` response are recoverable. Thoughts whose `save_thought` was interrupted (no response received) may or may not exist — that's acceptable. The oracle is: `recovered_ids ⊇ confirmed_ids`.

### `eval/recall_relevance.py`

Sample-based audit against a fixture corpus with known expected results.

**Test harness:** Same subprocess stdio approach as `crash_recovery.py` — spawn MCP server with a temp data repo, load the fixture corpus into it via `save_thought` calls, then run queries via `recall` and compare against expected results.

**Test isolation:** Temp `$FAVA_TRAILS_DATA_REPO` per run. The fixture corpus is loaded fresh each time to ensure deterministic state.

**Corpus design** (`eval/fixtures/corpus/`):
- 50 thought markdown files across 3 namespaces (decisions, observations, drafts)
- Covering varied topics: architecture decisions, bug findings, user preferences, status updates
- Each thought has realistic frontmatter (tags, relationships, source_type)

**Query-result mappings** (`eval/fixtures/expected.yaml`):
```yaml
queries:
  - query: "authentication decision"
    expected_ids: ["01ABC...", "01DEF..."]
    min_results: 1
  - query: "gotcha database"
    expected_ids: ["01GHI..."]
    scope_tags: ["gotcha"]
  - query: "status update"
    expected_ids: ["01JKL...", "01MNO..."]
    namespace: "drafts"
```

**Metrics calculated:**
- **Precision@k** (k=5, 10): What fraction of returned results are relevant?
- **Recall@k**: What fraction of known relevant thoughts were returned?
- **MRR** (Mean Reciprocal Rank): How high is the first relevant result?

**Baseline thresholds** (must pass for Spec 8 to be complete):
- Precision@5 >= 0.6 for keyword `recall` queries
- Recall@10 >= 0.8 for keyword `recall` queries
- If semantic recall (Spec 7) is available: Precision@5 >= 0.7, Recall@10 >= 0.9

**Output:** JSON report to stdout + `eval/results/recall_baseline.json`:
```json
{
  "tool": "recall",
  "queries_tested": 15,
  "precision_at_5": 0.73,
  "recall_at_10": 0.87,
  "mrr": 0.82,
  "failures": []
}
```

## Done Criteria

- `crash_recovery.py` passes — zero data loss after SIGKILL
- `recall_relevance.py` produces precision/recall/MRR metrics for known corpus
- Baseline thresholds met for keyword recall
- Both scripts runnable standalone (`python eval/crash_recovery.py`)
- Fixture corpus checked into `eval/fixtures/`
- Results written to `eval/results/` (gitignored)

## Out of Scope

- CI/CD integration (future)
- Performance benchmarking (future)
- Semantic recall baselines (deferred to Spec 7 integration — run `recall_relevance.py` again after Spec 7 merges)
