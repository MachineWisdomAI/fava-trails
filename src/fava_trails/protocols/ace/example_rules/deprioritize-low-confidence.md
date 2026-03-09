---
source_type: user_input
confidence: 0.85
metadata:
  tags: [ace-playbook, confidence-floor]
  extra:
    rule_type: confidence_floor
    match:
      confidence_lt: 0.3
    action:
      deprioritize: 0.6
    weight: 5
    helpful_count: 0
    harmful_count: 0
    section: quality_control
    description: Deprioritize highly uncertain thoughts during recall
---
# Deprioritize Low-Confidence Thoughts

Thoughts with confidence below 0.3 are pushed down in recall rankings.
Very low confidence typically indicates speculative inferences or unverified
observations that shouldn't dominate recall results.

The `deprioritize` action applies a 0.6x multiplier (further reduced by
Laplace smoothing until the rule proves itself via feedback).

## When to Adjust

- If too many valid low-confidence thoughts are being buried, lower the
  `confidence_lt` threshold (e.g., 0.2) or increase `helpful_count`.
- If low-confidence noise is still getting through, increase the
  `deprioritize` factor (e.g., 0.4) or raise the threshold.
