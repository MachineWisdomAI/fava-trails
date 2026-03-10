---
source_type: user_input
confidence: 0.9
metadata:
  tags: [ace-playbook, retrieval-priority]
  extra:
    rule_type: retrieval_priority
    match:
      tags_include: [important]
      tags_exclude: [archived]
    action:
      boost: 2.0
    weight: 15
    helpful_count: 12
    harmful_count: 1
    section: task_guidance
    description: Surface thoughts explicitly tagged as important (and not archived)
---
# Boost Important, Non-Archived Thoughts

Thoughts tagged `important` (but not `archived`) receive a 2.0x base boost.
With helpful_count=12 and harmful_count=1, the Laplace-smoothed ratio is
(12+1)/(12+1+2) = 13/15 ≈ 0.867, giving an effective multiplier of ≈ 1.73x
(clamped to max 2.0).

This rule has accumulated positive feedback and is well-calibrated. It
demonstrates how feedback counters evolve: start at 0/0 (effective boost ≈ 1x),
accumulate helpful signals, and the rule's influence grows toward the configured
boost ceiling.

## Tagging Convention

- Add `important` tag to thoughts that should consistently surface in recall
- Add `archived` tag to retire a thought from active ranking without deleting it
- The `tags_exclude: [archived]` prevents revived archived content from being boosted
