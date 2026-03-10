# Implementation Plan: RLM MapReduce Hooks

Full plan in FAVA Trails: `mwai/eng/fava-trails/codev-assets/plans/19-rlm-reference` (thought `01KKA9ZE7H3KN518MYJ0T5JFDN`)

## Phases (Machine Readable)

```json
{
  "phases": [
    {"id": "phase_1", "title": "configure + before_save validation"},
    {"id": "phase_2", "title": "after_save batch progress counter"},
    {"id": "phase_3", "title": "on_recall deterministic ordering"},
    {"id": "phase_4", "title": "Pipeline integration, orchestrator, README"}
  ]
}
```

## Phase 1: configure + before_save validation
- **Files**: `src/fava_trails/protocols/rlm/__init__.py`, `tests/test_rlm.py`
- **Dependencies**: None
- **Done**: before_save rejects missing mapper_id, advises missing batch_id, rejects short content

## Phase 2: after_save batch progress counter
- **Files**: `src/fava_trails/protocols/rlm/__init__.py`, `tests/test_rlm.py`
- **Dependencies**: Phase 1
- **Done**: Distinct mapper counting, reduce-ready signal, batch reset, concurrent safety

## Phase 3: on_recall deterministic ordering
- **Files**: `src/fava_trails/protocols/rlm/__init__.py`, `tests/test_rlm.py`
- **Dependencies**: Phase 1
- **Done**: mapper_id + created_at sort, RecallSelect + Annotate

## Phase 4: Pipeline integration, orchestrator, README
- **Files**: `src/fava_trails/protocols/rlm/orchestrator.py`, `src/fava_trails/protocols/rlm/README.md`, `tests/test_rlm.py`
- **Dependencies**: Phases 1-3
- **Done**: Pipeline tests pass, README complete, orchestrator reference script
