# Implementation Plan: ACE Playbook Hooks (Curator Pattern)

## Metadata
- **Spec**: 18-ace-reference
- **Epic**: 0007a-context-engineering
- **Consultation**: GPT 5.3 Codex (FOR 8/10), Gemini 3.1 Pro (AGAINST 9/10)
- **Protocol**: ASPIR
- **Branch**: feature-18-ace-reference
- **FAVA Trails**: `01KKAA7ACN1SRR56YHWYBG33FV` in `mwai/eng/fava-trails/codev-assets/plans/18-ace-reference`

## Overview

Implement the ACE Curator pattern as a FAVA Trails protocol hook module. Six lifecycle hooks provide playbook-driven recall reranking, save-time quality checks, and observer telemetry. Pure Python, zero external dependencies.

## Consultation Changes (vs Spec 18 v4)
- **Added `after_propose` hook** (unanimous) — rules enter preferences/ via propose_truth
- **Score clamping** [0.5, 2.0] — prevents runaway ranking
- Multi-process cache concern deferred (single-process stdio for v1)

## Phases

```json
{
  "phases": [
    {"id": "phase_1", "title": "PlaybookRule dataclass and parser (rules.py)"},
    {"id": "phase_2", "title": "Hook module (__init__.py) with all 6 lifecycle hooks"},
    {"id": "phase_3", "title": "Tests (test_ace.py)"},
    {"id": "phase_4", "title": "README and example rules"}
  ]
}
```

### Phase 1: PlaybookRule + Parser
- **Objective**: Implement rule engine with ACE-style feedback counters
- **Files**: `src/fava_trails/protocols/ace/rules.py`
- **Dependencies**: None
- **Success Criteria**: PlaybookRule matches/evaluates correctly, _parse_rules handles malformed entries gracefully
- **Tests**: Unit tests for matches(), evaluate(), _parse_rules()

Details:
- `PlaybookRule` dataclass: name, rule_type, match, action, weight, helpful_count, harmful_count, section, description, source_thought_id
- `matches(thought)` — AND logic: source_type, confidence_lt, tags_include, tags_exclude, age_lt_days
- `evaluate(thought)` — Multiplicative factor with Laplace-smoothed ratio, clamped to [0.5, 2.0]
- `_parse_rules(raw_thoughts)` — Reads metadata.extra, skips malformed with warning

### Phase 2: Hook Module with 6 Lifecycle Hooks
- **Objective**: Implement all hooks following SECOM patterns
- **Files**: `src/fava_trails/protocols/ace/__init__.py`
- **Dependencies**: Phase 1
- **Success Criteria**: All hooks use correct Event-Action types, cache works with TTL
- **Tests**: Hook function tests

Hooks:
1. `on_startup` — Return StartupOk, lazy warmup
2. `on_recall` — Lazy-load rules via TrailContext.recall("ace-playbook"), cache 5-min TTL, multiplicative scoring, RecallSelect + Annotate
3. `before_save` — Anti-pattern Warn + brevity bias Advise (decision < 80 chars)
4. `after_save` — Cache invalidation on ace-playbook tag + telemetry
5. `after_propose` — Cache invalidation on ace-playbook tag
6. `after_supersede` — Correction telemetry + cache invalidation

Config: `playbook_namespace` (str, default "preferences")

### Phase 3: Tests
- **Objective**: Comprehensive test coverage following test_secom.py patterns
- **Files**: `tests/test_ace.py`
- **Dependencies**: Phases 1 and 2
- **Success Criteria**: All tests pass
- **Tests**: TestConfigure, TestPlaybookRule, TestParseRules, TestOnStartup, TestOnRecall, TestBeforeSave, TestAfterSave, TestAfterPropose, TestAfterSupersede, TestPipelineIntegration

### Phase 4: README + Example Rules
- **Objective**: User-facing documentation and sample rules
- **Files**: `src/fava_trails/protocols/ace/README.md`, `src/fava_trails/protocols/ace/example_rules/*.md`
- **Dependencies**: Phases 1 and 2
- **Success Criteria**: README follows SECOM pattern, examples demonstrate all rule types
- **Tests**: Manual verification

## Risk Assessment
- **age_lt_days timezone**: Defensive try/except, default True on failure
- **Cache race**: GIL-protected dict assignment; first writer wins
- **Missed invalidation**: TTL backstop recovers within 5 minutes
- **Score explosion**: Clamped to [0.5, 2.0] per evaluation
