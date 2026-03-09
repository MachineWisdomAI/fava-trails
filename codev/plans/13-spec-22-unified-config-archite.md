# Implementation Plan: spec-22-unified-config-archite

## Overview

Consolidate hook configuration from `hooks/hooks.yaml` into the existing `config.yaml` /
per-trail `.fava-trails.yaml` hierarchy. Introduce a `ConfigStore` singleton for cached
global config access. Delete all `hooks/hooks.yaml` infrastructure.

Ref: FAVA Trails plan thought `01KK99KFDPX88P6AV4YAK575CD`

## Phases (Machine Readable)

```json
{
  "phases": [
    {"id": "phase_1", "title": "Model Consolidation"},
    {"id": "phase_2", "title": "ConfigStore Singleton"},
    {"id": "phase_3", "title": "Wire Hooks Through Config"},
    {"id": "phase_4", "title": "Test Updates and Cleanup"}
  ]
}
```

## Phase Breakdown

### Phase 1: Model Consolidation
- **Objective**: Move HookEntry/KNOWN_HOOKS to models.py, add hooks fields to GlobalConfig/TrailConfig
- **Files**: `src/fava_trails/models.py`, `src/fava_trails/hook_manifest.py`
- **Dependencies**: None
- **Success Criteria**: `from fava_trails.models import HookEntry, KNOWN_HOOKS` works; TrailConfig rejects non-empty hooks; HookRegistry.load_from_entries() works
- **Tests**: test_models.py, test_hook_manifest.py

### Phase 2: ConfigStore Singleton
- **Objective**: Introduce ConfigStore for cached global config; free functions become wrappers
- **Files**: `src/fava_trails/config.py`, `tests/conftest.py`
- **Dependencies**: Phase 1
- **Success Criteria**: ConfigStore.get() returns same instance; reset() clears cache; override() injects test config
- **Tests**: test_config.py ConfigStore lifecycle tests

### Phase 3: Wire Hooks Through Config
- **Objective**: Server loads hooks from ConfigStore.get().global_config.hooks; delete hooks/hooks.yaml logic
- **Files**: `src/fava_trails/server.py`, `src/fava_trails/tools/navigation.py`
- **Dependencies**: Phase 2
- **Success Criteria**: No hooks/hooks.yaml references remain; push strategy uses cached config
- **Tests**: Integration tests via existing test suite

### Phase 4: Test Updates and Cleanup
- **Objective**: Update all tests to use new APIs; add coverage for ConfigStore and new model fields
- **Files**: `tests/test_hook_manifest.py`, `tests/test_hooks.py`, `tests/test_models.py`, `tests/test_config.py`
- **Dependencies**: Phase 3
- **Success Criteria**: `uv run pytest -v` all pass; `uv run ruff check` clean
- **Tests**: Full test suite

## Dependency Map

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4
```

## Risk Assessment

- Singleton test isolation: Mitigated by autouse reset_config_store fixture
- Circular imports from KNOWN_HOOKS move: Mitigated by colocating in models.py (plain frozenset)
- Mutable default shared-state: Fixed with Field(default_factory=...) in Phase 1
