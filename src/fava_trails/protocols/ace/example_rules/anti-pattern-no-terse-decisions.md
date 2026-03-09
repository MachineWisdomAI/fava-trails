---
source_type: user_input
confidence: 0.9
metadata:
  tags: [ace-playbook, anti-pattern]
  extra:
    rule_type: anti_pattern
    match:
      source_type: decision
      tags_exclude: [reviewed]
    action: {}
    weight: 20
    helpful_count: 0
    harmful_count: 0
    section: quality_control
    description: Warn when saving unreviewed decisions — complements the built-in brevity advisory
---
# Anti-Pattern: Unreviewed Decisions

Warns when a `decision` thought is saved without a `reviewed` tag. This
complements the built-in brevity-bias advisory (< 80 chars). Together they
enforce a lightweight review discipline: decisions should be explicitly marked
as reviewed before saving.

## Interaction with Built-in Hooks

The ACE module already warns on terse decisions (< 80 chars) via the
`ace_brevity_bias` advisory. This anti-pattern rule adds a parallel check
for the `reviewed` tag — both can fire simultaneously.

`anti_pattern` rules do NOT affect `on_recall` scoring (they always return
1.0 multiplier). They only surface as `Warn` actions in `before_save`.

## Workflow

1. Draft a decision → ACE warns if unreviewed or terse
2. Agent reviews and adds `reviewed` tag via `update_thought`
3. Rule no longer fires on next save
