# Specification: Open-Source Readiness for Early Adopters

## Metadata
- **ID**: spec-2026-02-24-oss-readiness
- **Status**: draft
- **Created**: 2026-02-24
- **Protocol**: SPIR
- **Epic**: 0005a-adoption
- **Prerequisites**: Spec 12 (rebrand to FAVA Trails) must be integrated first

## Clarifying Questions Asked

1. **Should we use Apache 2.0 or MIT?** — Owner noted AI ecosystem trending MIT. Consensus (3-way: GPT-5.2, Gemini 3 Pro, Grok) recommends Apache 2.0 (2-1 vote). Reasoning: FAVA Trails is audit infrastructure accessed over stdio/JSON-RPC, not a library — MIT's "no infection" advantage doesn't apply. Apache 2.0 provides patent protection and enterprise credibility.
2. **Should the repo stay private (invite-only) or go fully public?** — Owner concerned private collaborators could clone and claim ownership. Unanimous consensus: go fully public. Public git history provides timestamped provenance that private sharing cannot. "Obscurity is a liability, not a defense."
3. **What's the minimum checklist for early adopters?** — See Solution Approaches below. Consensus identified additional items beyond the original proposal (CI/CD, issue templates, version metadata).

## Problem Statement

FAVA Trails is feature-complete enough for early adopters (16 MCP tools, 127 tests, comprehensive docs, auto-injected server instructions) but the repo lacks the scaffolding external users expect from an open-source project. The repo is currently private, has no CI/CD, no contribution guidelines, broken README examples, and stale package metadata. These are all solvable in a single pass.

The owner also needs to decide the license and visibility strategy before opening to external users.

## Current State

- **Repo visibility**: Private on GitHub (MachineWisdomAI/fava-trails)
- **License**: Apache 2.0 file exists, but `pyproject.toml` has no `license` field (`pip show` says "License: UNKNOWN")
- **Version**: `pyproject.toml` says `0.1.0` but git tags are at `v0.3.2` — inconsistent
- **README examples**: `save_thought()` / `propose_truth()` / `recall()` examples omit the required `trail_name` parameter — guaranteed "broken on arrival" for new users
- **CI/CD**: None — 127 tests exist but no automation to enforce them on PRs
- **Issue templates**: None — JJ (Jujutsu) is niche, users will hit environment issues
- **CONTRIBUTING.md**: Missing
- **CHANGELOG.md**: Missing
- **GitHub topics**: None — zero discoverability
- **GitHub Releases**: None — only git tags exist
- **pyproject.toml metadata**: Missing `authors`, `project.urls`, `license`

## Desired State

After this spec is implemented (post-rebrand):

1. The repo is **public** on GitHub as `MachineWisdomAI/fava-trails`
2. **Apache 2.0** license is properly declared in pyproject.toml and LICENSE
3. **README examples work on first try** — all include `trail_name`
4. **CI runs on every PR** via GitHub Actions (`uv run pytest`)
5. **Issue templates** guide users to provide JJ version, OS, and reproduction steps
6. **CONTRIBUTING.md** explains how to run tests, code style, and PR expectations
7. **CHANGELOG.md** documents releases from v0.1.0 through current
8. **GitHub topics** set for discoverability (`mcp`, `ai-agents`, `memory`, `jujutsu`, `python`, `mcp-server`)
9. **GitHub Release** created for the current version with release notes
10. **pyproject.toml** has complete metadata (`license`, `authors`, `project.urls`, correct `version`)

## Stakeholders
- **Primary Users**: AI agent developers evaluating FAVA Trails for agent memory
- **Secondary Users**: MCP ecosystem builders, framework authors integrating memory
- **Technical Team**: Machine Wisdom (architect + builders)
- **Business Owner**: Younes (Machine Wisdom Solutions Inc.)

## Success Criteria
- [ ] Repo is public at `MachineWisdomAI/fava-trails` (post-rebrand name)
- [ ] `pip show fava-trails` displays correct license, version, and URLs
- [ ] README "Use it" examples execute without errors when copy/pasted
- [ ] GitHub Actions CI passes on a fresh PR
- [ ] Issue templates render correctly on GitHub
- [ ] CONTRIBUTING.md, CHANGELOG.md exist and are linked from README
- [ ] GitHub topics set and repo appears in topic searches
- [ ] GitHub Release exists for current version
- [ ] All 127+ tests pass
- [ ] No secrets, internal paths, or sensitive data exposed in public repo

## Constraints

### Technical Constraints
- Must complete **after** Spec 12 (rebrand) — all file paths, package names, and references will use the new `fava-trails` / `fava_trails` naming
- CI must handle JJ installation (JJ is not in standard package managers — `scripts/install-jj.sh` exists)
- Tests require JJ binary — CI workflow must install it first

### Business Constraints
- Apache 2.0 license — confirmed by 3-way consensus (patent protection for audit infrastructure)
- Copyright: Machine Wisdom Solutions Inc.
- No sensitive internal tooling references (codev/, Agent Farm, Pal MCP) should be exposed in ways that confuse external users

## Assumptions
- Spec 12 (rebrand) is integrated: repo is named `fava-trails`, package is `fava_trails`, entry point is `fava-trails-server`
- The `codev/` directory will ship with the public repo (transparency — specs/plans/reviews are non-sensitive)
- PyPI publishing is deferred to a follow-up (not blocking early adopters who install via `uv run --directory`)
- No SECURITY.md or CODE_OF_CONDUCT.md required for initial launch (can be added when community grows)

## Solution Approaches

### Approach 1: Single-Pass OSS Polish (Recommended)

**Description**: A single implementation pass that adds all missing OSS scaffolding in one commit series. Prioritizes items that directly affect the "first 5 minutes" experience.

**Deliverables**:

1. **pyproject.toml metadata** — Add `license`, `authors`, `project.urls`, fix `version`
2. **README.md examples** — Add `trail_name` to all tool call examples
3. **GitHub Actions CI** — `.github/workflows/test.yml` with JJ install + `uv run pytest`
4. **Issue templates** — `.github/ISSUE_TEMPLATE/bug_report.yml` with JJ version, OS, steps fields
5. **CONTRIBUTING.md** — How to: install deps, run tests, code style (ruff), PR expectations
6. **CHANGELOG.md** — Entries for all releases through current version
7. **GitHub topics + Release** — Set via `gh` CLI after repo is public

**Pros**:
- Everything ships at once — consistent first impression
- Small scope, all mechanical changes
- No functional/code changes required

**Cons**:
- Needs to wait for rebrand to complete
- CI workflow needs testing (JJ install in GitHub Actions is non-trivial)

**Estimated Complexity**: Low
**Risk Level**: Low

### Approach 2: Staged Rollout

**Description**: Ship docs/metadata first (private), then CI/templates, then go public.

**Pros**:
- Can test CI before going public
- Lower blast radius per step

**Cons**:
- Slower — delays the public launch
- More commits/coordination for no real benefit
- Going public is the whole point — staging doesn't help early adopters

**Estimated Complexity**: Low
**Risk Level**: Low

**Recommendation**: Approach 1. The scope is small enough that staging adds overhead without reducing risk.

## Open Questions

### Critical (Blocks Progress)
- [x] License choice: Apache 2.0 vs MIT — **Resolved: Apache 2.0** (3-way consensus, 2-1)
- [x] Repo visibility: private vs public — **Resolved: Public** (unanimous consensus)

### Important (Affects Design)
- [ ] Should `codev/` directory be mentioned in CONTRIBUTING.md or ignored for external contributors?
- [ ] Should the CI workflow also run ruff lint, or just pytest?

### Nice-to-Know (Optimization)
- [ ] Should we create a GitHub Discussions tab for early adopter Q&A?
- [ ] Should we add a "Star History" or "Used By" badge to README?

## Performance Requirements
N/A — no runtime changes. CI should complete in < 5 minutes.

## Security Considerations
- **Audit public repo for secrets** before flipping visibility — check `.env` patterns, hardcoded paths, internal URLs
- **No credentials in CI** — tests don't require network access or API keys
- **Apache 2.0 patent grant** protects users from patent claims on the versioning mechanisms

## Test Scenarios

### Functional Tests
1. Copy README "Use it" examples into a fresh MCP session — they work without modification
2. `pip show fava-trails` displays correct license, version, homepage
3. Open a GitHub issue using the bug report template — all fields render correctly
4. Push a PR — CI runs and passes

### Non-Functional Tests
1. CI completes in < 5 minutes
2. No sensitive data exposed (grep for internal paths, API keys, hostnames)

## Dependencies
- **Spec 12 (rebrand)**: Must be integrated — this spec uses post-rebrand naming throughout
- **JJ binary**: CI needs `scripts/install-jj.sh` to work in GitHub Actions (Ubuntu runner)
- **GitHub CLI (`gh`)**: Used to set topics, create releases

## References
- [3-way consensus results](#expert-consultation) (below)
- FAVA Trail thought `01KJ83Z750Y7TED496WNC5DW73` (claude-desktop, `mwai/eng/fava-trails`) — cross-agent review on license strategy and PyPI priority
- Spec 12: `codev/specs/12-rebrand-fava-trails.md`
- Epic 0005a: `codev/epics/0005a-adoption.md`

## Risks and Mitigation
| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|-------------------|
| JJ install fails in GitHub Actions | Medium | High | Test the install script in a Ubuntu runner; cache JJ binary between runs |
| Sensitive internal data exposed when going public | Low | High | Audit with `grep` for internal paths, API keys, hostnames before visibility flip |
| Early adopters hit JJ installation issues locally | High | Medium | Issue templates + install-jj.sh script + FAQ doc already exists |
| Someone forks and claims ownership | Low | Low | Public git history provides timestamped provenance; Apache 2.0 copyright notice; signed tags |

## Expert Consultation

**Date**: 2026-02-24
**Models Consulted**: GPT-5.2 (for), Gemini 3 Pro (against), Grok (neutral)
**Continuation ID**: `d8fc8320-6703-4607-97d0-7fce09484de1`

### Decision 1: Readiness Checklist — Unanimous agreement with additions
All three models confirmed the proposed checklist. Additional items identified:
- CI/CD (GitHub Actions) — flagged by Gemini 3 Pro as critical
- Issue templates for JJ environment issues — flagged by Gemini 3 Pro
- Fix pyproject.toml version mismatch (0.1.0 vs v0.3.2) — flagged by GPT-5.2 and Grok
- Add `authors`, `project.urls` to pyproject.toml — flagged by Gemini 3 Pro and Grok
- Signed git tags + GitHub Releases — flagged by GPT-5.2
- Trademark note in README — suggested by GPT-5.2 (deferred)

### Decision 2: License — Apache 2.0 (2-1)
- **GPT-5.2 (FOR)**: Patent grants signal seriousness for infrastructure; NOTICE overhead only applies if you ship a NOTICE file (FAVA Trails doesn't)
- **Gemini 3 Pro (AGAINST stance, but agreed)**: "Audit infrastructure" domain demands patent protection; standalone server accessed via stdio — MIT's "no infection" argument doesn't apply
- **Grok (NEUTRAL)**: Recommended MIT for ecosystem alignment, but acknowledged Apache 2.0's stronger protections

### Decision 3: Visibility — Public (unanimous)
- GPT-5.2: Public provenance is "excellent evidence" for IP disputes; private sharing increases "soft appropriation" risk
- Gemini 3 Pro: "Obscurity is a liability, not a defense"; "the value isn't the Python lines, it's the standard and the brand"
- Grok: Public timestamps prove authorship; private invites lack public proof

All consultation feedback has been incorporated directly into the relevant sections above.

### Cross-Agent Review: Claude Desktop (FAVA Trail thought `01KJ83Z750Y7TED496WNC5DW73`)

**Source**: `mwai/eng/fava-trails` scope, `claude-desktop` agent, confidence 0.9

Key contributions beyond the 3-way consensus:

1. **Architectural analogy for Apache 2.0**: FAVA Trail's correct peer group is not LangChain/LlamaIndex (libraries that agents embed, which reasonably choose MIT) — it's Postgres, Redis, Kafka (infrastructure agents *connect to*, which universally use licenses with explicit patent grants). The server communicates over stdio/JSON-RPC; its license never touches agent code.

2. **Patent grant specifics**: Contributors license patents necessarily infringed by their contribution. For enterprise audit use cases (healthcare, finance, legal), conservative legal teams flag MIT's silence on patents as ambiguity — Apache 2.0 clears procurement review without friction.

3. **PyPI should not be deferred**: "Lowering the `pip install` path from 'clone, build, configure' to a single command is the difference between an engineer evaluating the project and one who intends to but never gets around to it." Trial friction is the whole game at early-adopter stage. Recommendation: treat PyPI as near-term critical, not a deferral.

4. **Go public reasoning**: Keeping private until "ready" weakens IP provenance — a bad actor who encounters the project through any channel can fork, strip history, and publish first. Public + Apache 2.0 + signed tags = clean, cryptographically verifiable provenance.

This review reinforces the consensus decisions and escalates PyPI publishing from deferred to near-term.

## Approval
- [ ] Technical Lead Review
- [ ] Product Owner Review
- [ ] Stakeholder Sign-off
- [x] Expert AI Consultation Complete

## Notes

- This spec intentionally uses post-rebrand naming (`fava-trails`, `fava_trails`) throughout. All implementation happens after Spec 12 is integrated.
- **PyPI publishing** (`pip install fava-trails`) is near-term critical per the Desktop cross-agent review — trial friction at early-adopter stage is the difference between evaluation and abandonment. Include in the plan as a final phase or fast-follow TICK.
- The `codev/` directory ships publicly. It demonstrates the development methodology and provides transparency. External contributors are not expected to use SPIR — CONTRIBUTING.md will explain the simpler PR workflow.

---

## Amendments

<!-- When adding a TICK amendment, add a new entry below this line in chronological order -->
