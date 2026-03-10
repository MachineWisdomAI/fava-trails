---
source_type: user_input
confidence: 0.9
metadata:
  tags: [ace-playbook, retrieval-priority]
  extra:
    rule_type: retrieval_priority
    match:
      source_type: decision
      age_lt_days: 7
    action:
      boost: 1.5
    weight: 10
    helpful_count: 0
    harmful_count: 0
    section: task_guidance
    description: Recent decisions rank higher than older ones — they're more likely to still be valid
---
# Boost Recent Decisions

Boost decisions made in the last 7 days. Recent decisions are more likely to
reflect current context and still be actionable — older decisions may have been
superseded by new information.

The 1.5x boost combined with Laplace smoothing means this rule has mild effect
at first (helpful/harmful both 0 → ratio=0.5 → effective boost=0.75). As the
rule accumulates positive feedback (helpful_count increases), the boost grows
toward the configured 1.5x ceiling.

## How to Use

Save this thought via `save_thought` with the frontmatter above, then promote
via `propose_truth`. Update `helpful_count` / `harmful_count` as you observe
whether it improves recall quality.
