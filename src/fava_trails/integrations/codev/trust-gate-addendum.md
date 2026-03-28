## Codev Artifact Validation

This thought is a codev development artifact. Apply these additional checks
based on the artifact type inferred from scope and tags.

### Artifact Type Detection
- Scope contains `/specs/` → Specification
- Scope contains `/plans/` → Plan
- Scope contains `/reviews/` → Review
- Fallback: infer from tags (codev-spec, codev-plan, codev-review) or content

### Specifications — REJECT if:
- No concrete problem articulated (solution without problem)
- Acceptance criteria are vague or unmeasurable
- Contains implementation details (file paths, code, phase breakdowns)

### Plans — REJECT if:
- Single monolithic block with no phase decomposition
- Phases lack "done" criteria
- Contains time or effort estimates

### Reviews — REJECT if:
- No critical reflection (pure celebration)
- Missing lessons learned or retrospective
- No comparison against original spec intent

### Calibration
- Brevity is fine — substance over length.
- Don't penalize style or formatting choices.
- Lean APPROVE with a note rather than REJECT when borderline.
