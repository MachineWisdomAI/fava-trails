# FAVA Trails: Frequently Asked Questions

**Federated Agentic Versioned Audit Trail**
*For agent framework authors, MLE/AI engineers, and agentic memory researchers*

---

## The Problem

### Why do agents need a dedicated memory system? Can't I just use a vector database?

You can. And you'll hit the same wall everyone else hits at about hour one.

DoltHub's independent testing measured the phenomenon precisely: raw coding agent sessions max out at approximately one hour before the agent loses coherence. The reason is architectural, not a model limitation. Vector databases optimize for semantic similarity — "find me something *like* this." But production agents need semantic correctness — "find me the *exact* thing we established on Tuesday, including why we changed our mind about it on Wednesday."

When your agent writes a flawed hypothesis (Thought A), then corrects it (Thought A'), a vector search for the topic retrieves *both* — because they're semantically identical. This is what we call Contextual Flattening. Your agent now has contradictory beliefs with no mechanism to distinguish which one is current.

FAVA Trails solves this with supersession tracking: Thought A gets tombstoned when Thought A' is created. Default retrieval never surfaces superseded thoughts. The agent sees only the current truth unless it explicitly asks for the full lineage.

### What is the "Correctness-Congruence Gap"?

Technical correctness asks: "Is this response schema-compliant and internally consistent?" That's a closed-world problem you can solve with validation rules.

Intent alignment (what we call Congruence) asks: "Is this response consistent with the historical context, unstated constraints, and strategic direction established across months of prior work?" That's an open-world problem requiring temporal provenance that flat retrieval systems structurally cannot provide.

FAVA Trails bridges this gap by making version history, relationship graphs, and provenance chains queryable. Every memory carries its full lineage: what was believed, when it changed, why it changed, and who approved the change.

### What is "memory poisoning" and how does FAVA Trails prevent it?

Memory poisoning occurs when an agent's false beliefs — hallucinations, outdated facts, incorrect inferences — enter shared memory and subsequently inform other agents' reasoning. In systems without governance, every agent write immediately becomes "truth." Bad data propagates exponentially.

FAVA Trails prevents this through the **Trust Gate** — a gated promotion workflow borrowed directly from software engineering's pull request model. Agents work in isolated draft branches. Their drafts are invisible to other agents. When an agent wants to promote a belief to shared truth, it submits a proposal that passes through a validation gate (a Critic Agent, a human reviewer, or both) before it becomes visible to the broader system.

If the Trust Gate rejects the proposal, the hallucination stays contained in draft. It never enters shared memory. No cleanup required. No downstream contamination.

This is not post-hoc rollback — it is **containment at the source**. The hallucination never becomes shared "truth" in the first place. Note: the Trust Gate reduces blast radius; it does not eliminate hallucinations entirely. A misconfigured gate or a sufficiently convincing hallucination can still pass review. Defense-in-depth (multiple reviewers, policy-based strictness per namespace, human override for high-stakes domains) is the correct mitigation.

### How does FAVA Trails relate to Context Engineering protocols like SECOM or ACE?

Academic protocols like Microsoft's SECOM (Segmentation and Compression, ICLR 2025) or Stanford's ACE (Agentic Context Engine) define *what* to do with context — compress memories, curate retrieval, manage information density — but leave the production substrate unspecified. Where do compressed memories live? How do you version them? What happens when compression fails mid-operation?

FAVA Trails provides the versioned substrate and the **Event-Action Pipeline** (lifecycle hooks) to run these protocols safely. Hooks fire at key lifecycle points (`before_propose`, `before_save`, `on_recall`, etc.) and return typed actions (`Mutate`, `Advise`, `RecallSelect`) that the pipeline executes atomically.

For example, the built-in [SECOM protocol](../src/fava_trails/protocols/secom/README.md) uses a Write-Once, Read-Many (WORM) optimization: the `before_propose` hook compresses content inline via LLMLingua-2 (extractive token-level compression, zero hallucination) before the thought is committed to its permanent namespace. This avoids read-path latency entirely, amortizes compression cost from O(recalls × thoughts) to O(promotes), and preserves the original verbose draft in the Jujutsu commit history. If compression fails, `fail_mode: open` lets the thought through unchanged — the operation never blocks.

Install with `pip install fava-trails[secom]` and add a `hooks:` entry to your data repo's `config.yaml`. See the [Protocols section](../README.md#protocols) for quick start.

**Known limitation**: SECOM's extractive token-level compression operates at the token level and has no notion of syntactic structure. JSON objects, YAML blocks, and fenced code blocks can be silently destroyed at promote time. Use the `secom-skip` tag to opt out of compression for any thought containing structured data — the `before_save` hook will warn you when it detects structured content without this tag.

---

## The Architecture

### How is this different from just using Git for agent memory?

Three critical differences.

**Crash-proof by design.** Git maintains a "dirty working copy" between explicit commits. If your agent crashes, that uncommitted work is lost. FAVA Trails's architecture requires automatic persistence — every state change is durably written before the operation returns. There is no concept of unsaved work.

**Conflict-tolerant storage.** Git blocks operations when conflicts occur. An agent cannot stop to resolve merge conflicts. FAVA Trails requires that contradictory beliefs be storable as structured data — the system records the conflict as a first-class artifact for later resolution rather than halting the agent's workflow.

**Governance workflows.** Git's branch protection rules exist but are designed for human developers. FAVA Trails's Trust Gate is designed for autonomous agents: automated validation, configurable strictness per knowledge domain, and human override capability for high-stakes decisions.

### What is the Trust Gate, concretely?

The Trust Gate is a configurable validation pipeline that evaluates proposed memories before they enter shared truth. In its simplest form, it's an LLM-based Critic Agent that checks for factual consistency, schema compliance, and alignment with existing shared knowledge.

The key design properties:

- **Async by default.** The proposing agent continues working in draft while the Trust Gate evaluates. It is not a blocking operation.
- **Policy-configurable.** Different namespaces can have different strictness levels. Client-facing facts might require human approval; internal observations might auto-approve if the Critic Agent gives a confidence score above threshold.
- **Rejection is non-destructive.** A rejected proposal stays in draft with reviewer feedback attached. The agent can revise and resubmit.
- **Auditable.** Every Trust Gate decision (accept, reject, revision request) is logged with rationale.

### What is the Pull Daemon?

The Pull Daemon is a planned sidecar process (design goal, not yet deployed) that will continuously synchronize each agent's working context with shared truth. It will run a periodic sync loop (default: every 30 seconds) that rebases the agent's draft branch on top of the latest accepted shared truth.

In the current release, agents call the `sync` MCP tool manually to pull latest shared truth. The Pull Daemon will automate this — when Agent A updates the project budget from "Low" to "High" and that update passes the Trust Gate, Agent B's Pull Daemon will pick up the change and rebase B's draft on top of the new truth. Agent B's reasoning then operates against the updated budget.

If the rebase creates a conflict (B was working with assumptions about the old budget), the conflict is surfaced to B as structured data rather than silently swallowed.

### Why version control instead of a database?

Databases optimize for current state. Version control optimizes for state evolution. In agentic workflows, state evolution *is* the product.

The critical capabilities that VCS provides natively but databases require custom engineering for:

- **Branching** — isolated workspaces that don't pollute shared state until explicitly merged.
- **Merge gating** — workflow enforcement as a first-class primitive, not an application concern.
- **History traversal** — "What did we believe about X three days ago?" is a native query, not a schema design exercise.
- **Atomic bulk discard** — "This entire 50-step investigation was wrong, delete all of it" is a single operation with zero residue.
- **Diff** — "What changed between Tuesday and today?" without scanning every record.

Database-backed systems can be engineered to provide some of these capabilities, but they're fighting the substrate rather than working with it. VCS was *designed* for exactly this class of problem.

---

## For Agent Framework Authors

### How do I integrate FAVA Trails with my agent framework?

FAVA Trails exposes all memory operations as **MCP (Model Context Protocol) tools**. If your framework speaks MCP, integration is a configuration change, not a code change.

Core MCP tools:

| Tool | What It Does |
|------|-------------|
| `save_thought` | Persist a reasoning artifact to the agent's draft branch |
| `recall` | Retrieve memories by ID, keyword, semantic similarity, or relationship traversal |
| `propose_truth` | Submit draft memories for Trust Gate review |
| `sync` | Pull latest shared truth into the agent's working context |
| `forget` | Atomic discard of a reasoning branch |
| `learn_preference` | Capture human feedback as a versioned preference |

Agents interact with memories as semantic objects (Markdown with structured frontmatter). They never see VCS commands, file paths, or storage internals.

### What does integration look like for large-scale autonomous agent systems?

For ML engineering agents running long-horizon tasks (12+ hour Kaggle competitions, multi-day model development) on infrastructure like serverless GPU clusters, FAVA Trails addresses three specific failure modes:

1. **Session persistence across context window resets.** When the context window fills and the agent needs to continue, FAVA Trails provides the full history of what was tried, what worked, what didn't, and why — reconstructable from versioned memory rather than lost when the window rolls over.

2. **Experiment branch isolation.** The agent can branch three parallel hypotheses (different model architectures, different feature engineering approaches) without cross-contamination. Each branch carries its own reasoning chain. The winning branch merges to main; the losing branches are atomically discarded.

3. **Preventing re-exploration of dead ends.** Supersession tracking means that when a hyperparameter search proves fruitless and is explicitly abandoned, future recall queries will not resurface that abandoned line of reasoning. The agent doesn't waste tokens re-discovering that "learning rate 0.1 diverges" if that was already established and marked as superseded.

### Can I use FAVA Trails as a drop-in replacement for my current memory backend?

FAVA Trails is designed to support adapter patterns for common memory interfaces. A planned mapping layer will map `search()` to `recall_semantic` + `recall`, `readFile()` to `get_thought`, and `sync()` to `sync`.

For frameworks with custom memory abstractions, the MCP interface is the universal integration point today.

### What about performance? My agent loop runs at millisecond timescales.

FAVA Trails distinguishes between working memory (draft operations) and shared truth (promotion operations). Phase 1 latency targets, measured against single-agent local-disk workloads:

- **Draft save:** < 50ms target. This is the "inner loop" — it must not block the agent's reasoning.
- **Draft recall:** < 100ms target. Context assembly is latency-sensitive.
- **Shared truth recall:** < 500ms p95. Includes semantic query + relationship traversal.
- **Trust Gate evaluation:** Async. The agent continues working while the gate evaluates.

These are design targets, not published benchmarks. Current prototype measurements will be published alongside the Phase 1 release with hardware specs, dataset sizes, and concurrency conditions.

The architecture separates the hot path (draft reads/writes) from the governance path (promotion, sync). Your agent loop stays fast.

---

## For MLE / ML Engineers

### How does this help with long-running ML experiments?

ML engineering agents face a specific version of the memory problem: experiments generate vast amounts of structured state (hyperparameters, metrics, error logs, dataset versioning) across multi-day runs. Current agents lose this state when sessions reset.

FAVA Trails's contribution:

- **Every experiment checkpoint is a versioned thought.** Hyperparameter configurations, training metrics, error traces — all persisted with full lineage. When the agent resumes after a crash or context reset, it can reconstruct exactly where it was.
- **Branching enables parallel hypothesis testing.** Three model architectures explored simultaneously, each on its own branch, with zero cross-contamination. Results merge back to main only when validated.
- **Dead-end marking prevents re-exploration.** When the agent discovers that a particular approach diverges, that finding is persisted with supersession semantics. The next agent session (or a different agent) won't waste compute re-discovering the same dead end.
- **Audit trail for reproducibility.** Every decision in the ML pipeline — why this learning rate, why that feature set, why we switched from ResNet to ViT — is traceable through the version history.

### My agents run in multi-agent swarms. How does FAVA Trails handle coordination?

Each agent gets its own isolated draft workspace. Agents never step on each other's work because drafts are invisible across workspaces. Coordination happens through shared truth:

1. Agent A discovers that Feature X improves accuracy by 3%. It promotes this finding through the Trust Gate.
2. The `sync` tool (or the planned Pull Daemon) propagates the accepted finding to all other agents.
3. Agent B, which was about to explore Feature X independently, sees the finding in its synced context and redirects its effort elsewhere.
4. Agent C, which had already started a conflicting hypothesis, sees the conflict surfaced as structured data and can decide how to resolve it.

This is eventual consistency with governance — the same pattern that lets teams of thousands of engineers coordinate through a shared monorepo.

---

## Security, Performance, and Enterprise Adoption

### How does FAVA Trails protect my proprietary data and corporate IP?

FAVA Trails follows an **Engine vs. Fuel** architecture that makes this a non-issue by design.

The MCP server (`fava-trails`) is a stateless, open-source engine. It contains zero knowledge about your organization. It processes requests, translates them to VCS operations, and returns structured results. It holds no state between calls.

Your actual data — the memory graph, the versioned repository, every thought your agents have ever produced — lives in a separate, isolated, locally controlled directory. This is the Fuel. You host it wherever your security policy requires: a local directory on the developer's machine, a private NFS mount, an air-gapped server, or a privately hosted Git remote for backup.

The architectural guarantee: **context never leaks into the tool's source code, its dependencies, or any external service.** No telemetry is collected. No cloud dependency exists. The MCP server is a pure function: input in, output out, nothing persisted. Your corporate IP stays on your infrastructure, governed by your access controls, backed up by your retention policies.

This separation also means you can update the engine independently of your data. Upgrading FAVA Trails's MCP server does not touch, migrate, or expose your repository.

### Doesn't wrapping memory in a Version Control System add latency and token bloat?

This is the most common objection from engineers who have worked with MemGPT, Goodmem, or similar systems — and it's a reasonable one. Raw VCS output is verbose, structurally complex, and would burn through context windows if surfaced directly.

FAVA Trails addresses this through a **Semantic Translation Layer** that sits between the agent and the VCS substrate.

What the agent sees: token-optimized, JSON-formatted semantic summaries returned through MCP tool calls. Structured recall results with relationship metadata, confidence scores, and supersession status. Clean, parseable, minimal.

What the agent never sees: raw `jj log` stdout, commit hashes, tree algebra, conflict markers, file paths, or any VCS-specific syntax. The Semantic Translation Layer intercepts every operation, handles the git-backend overhead locally (sub-second latency on local disk), and returns only the semantic payload.

The performance characteristics:

- **VCS operations** (commit, branch, rebase) happen at the file-system level, entirely within the MCP server process. They do not consume agent tokens.
- **Recall results** are pre-formatted as structured JSON with only the fields the agent requested. A typical recall response is 200-500 tokens, not a multi-kilobyte log dump.
- **The agent's prompt** contains memory summaries, not version history. Full lineage is available on demand (`include_superseded=True`) but is not included by default.

The design principle: the VCS is an implementation detail that provides crash-safety, branching, and audit guarantees. The agent interacts with a semantic memory API. The translation layer absorbs the complexity gap between these two interfaces.

---

## Technical Details

### What VCS does FAVA Trails use under the hood?

The current implementation uses JJ (Jujutsu) with a colocated Git backend. The PRD is deliberately substrate-agnostic — it defines *capability requirements* (crash-proof persistence, conflict-tolerant storage, persistent identity, atomic operations) rather than prescribing a specific tool.

JJ was selected for the MVP because it provides automatic snapshotting (crash-proof), first-class algebraic conflicts (conflict-tolerant), stable Change-IDs (persistent identity), and Git-compatible storage (ecosystem portability). The tradeoffs are documented in the *Architectural Choices* comparison analysis.

The MCP abstraction layer is thick enough that the VCS substrate can be swapped without changing the agent-facing API. Agents call `save_thought` and `recall`, not `jj commit` or `git push`.

### What is the data model?

Memories are called **Thoughts**. Each thought is an immutable Markdown file with structured YAML frontmatter:

```yaml
---
id: "01JMKR3V8GQZX4N7P2WDCB5HYT"    # ULID, stable across all operations
type: "decision"                         # decision | observation | preference | constraint
namespace: "client/acme"                 # isolation boundary
author: "agent-alpha"                    # which agent or human created this
superseded_by: null                      # links to successor if invalidated
relationships:
  - type: "DEPENDS_ON"
    target_id: "01JMKQ9F4RPBN2M6K8XDYA3GSW"
  - type: "REVISED_BY"
    target_id: "01JMKS7Y2HPQW5M8R3XECF6JZV"
tags: ["architecture", "model-selection"]
confidence: 0.85
intent_ref: "01JMKP5T3GNHW7L4J9YBZC2FRX"  # links to the original intent/spec
---

# Decision: Use ViT-Large for image classification

After testing ResNet-50 (see 01JMKQ9F4R...), we observed 3% accuracy improvement
with ViT-Large at acceptable inference latency...
```

Thoughts are append-only (immutable content, one exception: the `superseded_by` backlink). This prevents merge conflicts on content edits. When a thought needs correction, a new thought is created that supersedes the old one.

### What's on the roadmap?

**Phase 1 (Current):** Versioned thought store with crash-proof persistence, draft isolation, Trust Gate, supersession tracking, MCP integration.

**Phase 2:** Multi-agent synchronization (Pull Daemon), conflict interception, human-in-the-loop feedback capture, 1-hop relationship traversal.

**Phase 3:** Semantic vector index (derived from versioned store, rebuildable from history), temporal queries, data redaction.

**Phase 4:** Temporal Knowledge Graph (entity extraction, property graph projection, episodic summaries), enterprise federation.

### Is FAVA Trails open source?

FAVA Trails is developed by Machine Wisdom Solutions Inc. as an open-source project. The MCP server is a standalone Python package designed for integration with any MCP-compatible agent framework.

---

## The Competitive Landscape

### How does FAVA Trails compare to Beads/Dolt?

Steve Yegge's Beads system, now running on Dolt, demonstrated the 10× session duration improvement that validates the versioned memory thesis. Beads and FAVA Trails share the same foundational insight: agents need version-controlled structured data.

The key architectural difference: Beads uses SQL tables (Dolt) while FAVA Trails uses Markdown files with structured frontmatter. This reflects a design philosophy choice about cognitive ergonomics — LLMs are natively trained on and optimized for reading and writing Markdown, not managing SQL schemas and resolving row-level relational merges. Dolt provides versioned SQL primitives that *can* achieve gated merges and supersession through custom workflows, but these are application-layer concerns, not first-class primitives with built-in audit hooks and defaults. For orchestrating multi-agent swarms where work is rigidly defined as tickets, Dolt excels. For agents whose primary mode is reasoning in natural language, FAVA Trails's Markdown-native approach reduces cognitive overhead.

### How does FAVA Trails compare to Goodmem or other vector memory APIs?

Vector memory APIs (Goodmem, Mem0, Zep) provide zero-friction semantic retrieval. They are excellent for simple RAG over static documentation and optimized for the recall path.

FAVA Trails optimizes for a different surface: governance, provenance, and state evolution. When agents need temporal queries ("what did we believe last Tuesday?"), supersession tracking (hiding invalidated beliefs from default recall), draft isolation (preventing work-in-progress from polluting shared memory), or audit trails (proving provenance for compliance), these capabilities require versioned persistence as a foundational substrate.

Many memory tools optimize for recall speed and simplicity. FAVA Trails adds governance and provenance as first-class primitives alongside recall. These are complementary concerns, not competing ones — FAVA Trails can optionally use a vector store as a *derived index* for semantic queries, but the vector store is never the source of truth. It can be rebuilt from version history at any time.

### How does FAVA Trails compare to Graphiti or other temporal knowledge graphs?

Graphiti provides relationship tracking and temporal awareness — capabilities that FAVA Trails's roadmap includes in Phase 4 (Temporal Knowledge Graph). The difference is architectural: Graphiti is a graph database that agents write to directly. FAVA Trails's graph layer is a *derived projection* from the versioned store.

This distinction matters for trust and governance. In FAVA Trails, the graph can be rebuilt from the versioned history at any time. Graph corruption doesn't mean data loss. And the Trust Gate governs what enters the versioned store — the graph inherits those governance guarantees.

For teams that need graph intelligence today, FAVA Trails's Phase 1 schema includes typed relationships in thought frontmatter that can be projected to Graphiti or Neo4j as a downstream consumer.
