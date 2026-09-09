# FAVA Trails: Frequently Asked Questions

**Federated Agentic Versioned Audit Trail**
*For agent framework authors, MLE/AI engineers, and agentic memory researchers*

---

## The Problem

### Why do agents need a dedicated memory system? Can't I just use a vector database?

You can for similarity search. You will still need governance if agents write durable claims.

Vector databases optimize for semantic similarity — "find me something *like* this." Production agents often need provenance and currency — "find the *current approved* claim we established on Tuesday, including why we changed our mind on Wednesday."

When an agent writes a flawed hypothesis (Thought A), then proposes a correction (Thought A'), a pure similarity index often retrieves *both* because they are close in embedding space. That Contextual Flattening problem is about ranking and currency, not about FAVA inventing a better embedding model.

FAVA Trails addresses currency with **supersession lineage** and governed visibility: after durable approval of a successor, default governed recall hides the predecessor. That does **not** prove the replacement is true; it records that an approved replacement exists. Today's `recall` matcher itself is **lexical** (lowercased whitespace tokens as substrings with AND semantics) — not semantic similarity. See [retrieval-baseline.md](retrieval-baseline.md). A future search layer is discovery-only in [issue #59](https://github.com/MachineWisdomAI/fava-trails/issues/59); no embeddings product is selected there yet.

### What is the "Correctness-Congruence Gap"?

Technical correctness asks: "Is this response schema-compliant and internally consistent?" That's a closed-world problem you can solve with validation rules.

Intent alignment (what we call Congruence) asks: "Is this response consistent with the historical context, unstated constraints, and strategic direction established across months of prior work?" That's an open-world problem requiring temporal provenance that flat retrieval systems structurally cannot provide.

FAVA Trails bridges this gap by making version history, relationship graphs, and provenance chains queryable. Every memory carries its full lineage: what was believed, when it changed, why it changed, and who approved the change.

### What is "memory poisoning" and how does FAVA Trails reduce it?

Memory poisoning occurs when an agent's false beliefs — hallucinations, outdated facts, incorrect inferences — enter shared memory and subsequently inform other agents' reasoning. In systems without governance, every agent write immediately becomes "truth." Bad data propagates quickly.

FAVA Trails **reduces blast radius** with a gated promotion workflow (the **Trust Gate**), modeled on review-before-merge. Unapproved drafts stay out of default governed recall. Own drafts are visible only via explicit `mode="authoring"` on a server-configured identity. A shared MCP endpoint or shared data directory is still one trust boundary — not cryptographic isolation between concurrent callers on the same process.

When promotion is requested, an LLM critic and/or explicit human approval can reject or accept under a configured rubric. **Rubric-based review is not independent verification of project facts.** It does not know your agent's system prompt, safety policy, or private environment. A misconfigured gate or a convincing false claim can still be approved. Supersession after the fact records lineage; it does not establish that the replacement is true.

Rejected proposals remain drafts with feedback. Defense-in-depth (human approval on high-stakes namespaces, separate operator endpoints, caller-side verification of recalled claims) remains required.

### How does FAVA Trails relate to Context Engineering protocols like SECOM or ACE?

Academic protocols like SECOM (Segmentation and Compression; Tsinghua University and Microsoft, ICLR 2025) or ACE (Agentic Context Engineering; Stanford, UC Berkeley, and SambaNova, ICLR 2026) define *what* to do with context — compress memories, curate retrieval, manage information density — but leave the production substrate unspecified. Where do compressed memories live? How do you version them? What happens when compression fails mid-operation?

FAVA Trails provides the versioned substrate and the **Event-Action Pipeline** (lifecycle hooks) to run these protocols safely. Hooks fire at key lifecycle points (`before_propose`, `before_save`, `on_recall`, etc.) and return typed actions (`Mutate`, `Advise`, `RecallSelect`) that the pipeline executes atomically.

For example, the built-in [SECOM protocol](../src/fava_trails/protocols/secom/README.md) uses a Write-Once, Read-Many (WORM) optimization: the `before_propose` hook compresses content inline via LLMLingua-2 (extractive token-level compression — only original tokens survive) before the thought is committed to its permanent namespace. This avoids read-path latency entirely, amortizes compression cost from O(recalls × thoughts) to O(promotes), and preserves the original verbose draft in the Jujutsu commit history. If compression fails, `fail_mode: open` lets the thought through unchanged — the operation never blocks.

Install with `pip install fava-trails[secom]` and add a `hooks:` entry to your data repo's `config.yaml`. See the [Protocols section](../README.md#protocols) for quick start.

**Quick setup**: Use the CLI to avoid manual config editing:

```bash
fava-trails secom setup --write    # writes config.yaml + jj commit
fava-trails secom warmup           # pre-downloads model (~700MB)
fava-trails ace setup --write      # ACE playbook hooks
fava-trails rlm setup --write      # RLM MapReduce hooks
```

**Known limitation**: SECOM's extractive token-level compression operates at the token level and has no notion of syntactic structure. JSON objects, YAML blocks, and fenced code blocks can be silently destroyed at promote time. Use the `secom-skip` tag to opt out of compression for any thought containing structured data — the `before_save` hook will warn you when it detects structured content without this tag.

### Why does the first `propose_truth` take several minutes with SECOM enabled?

SECOM uses LLMLingua-2 (a ~700MB BERT-based token classifier from HuggingFace Hub) for extractive compression. The first call triggers a model download that can take 2–5 minutes depending on connection speed — subsequent calls use the cached model and complete in milliseconds.

To pre-download the model before agents encounter it:

```bash
fava-trails secom warmup
```

This downloads the model, runs a test compression, and reports the HuggingFace cache path. The warmup only needs to run once per machine. If you're deploying to a fresh environment (Docker, CI), run it during image build to avoid first-use latency in production.

---

## The Architecture

### How is this different from just using Git for agent memory?

Three critical differences.

**Crash-proof by design.** Git maintains a "dirty working copy" between explicit commits. If your agent crashes, that uncommitted work is lost. FAVA Trails's architecture requires automatic persistence — every state change is durably written before the operation returns. There is no concept of unsaved work.

**Conflict-tolerant storage.** Git blocks operations when conflicts occur. An agent cannot stop to resolve merge conflicts. FAVA Trails requires that contradictory beliefs be storable as structured data — the system records the conflict as a first-class artifact for later resolution rather than halting the agent's workflow.

**Governance workflows.** Git's branch protection rules exist but are designed for human developers. FAVA Trails's Trust Gate is designed for autonomous agents: automated validation, configurable strictness per knowledge domain, and human override capability for high-stakes decisions.

### What is the Trust Gate, concretely?

The Trust Gate is a configurable validation step that can run before a draft is promoted into shared records. In the shipped default, it is a **synchronous** LLM (or explicit human) rubric review of the **current proposed record only**: the configured prompt plus that record's content and selected redacted metadata. It does **not** load the shared corpus, does **not** independently verify project facts, and is **not** a guarantee that hallucinations never enter shared truth.

The key design properties today:

- **Synchronous on `propose_truth`.** When LLM review is enabled, `handle_propose_truth` awaits the single-record review (subject to `trust_gate_timeout_secs`) before promotion and return. The caller blocks on that tool call; there is no background async queue in the current release.
- **Limited context.** The LLM request is the configured Trust Gate prompt plus the thought under review — not a retrieval over existing shared knowledge.
- **Policy-configurable.** Review mode, model/provider, timeouts, and prompts are operator-configured (including local OpenAI-compatible endpoints). Different deployments can require human approval or skip LLM review entirely.
- **Rejection is non-destructive.** A rejected proposal stays in draft with reviewer feedback attached. The agent can revise and resubmit.
- **Auditable.** Trust Gate verdicts and reasoning are returned on the tool response and can be logged by operators.

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
| `save_thought` | Persist a reasoning artifact to the agent's draft namespace |
| `recall` | Lexical search: whitespace-separated query tokens must each appear as substrings in content/metadata; optional relationship expansion; governed/authoring/history visibility |
| `get_thought` | Retrieve one record by ULID |
| `propose_truth` | Submit draft memories for Trust Gate or explicit human approval |
| `sync` | Pull latest shared truth into the agent's working context |
| `forget` | Atomic discard of a reasoning branch |
| `learn_preference` | Capture human feedback as a versioned preference |

Agents interact with memories as Markdown objects with structured frontmatter. They never see VCS commands or raw tree algebra. `recall` is not semantic similarity search; measured behavior is in [retrieval-baseline.md](retrieval-baseline.md).

### What does integration look like for large-scale autonomous agent systems?

For ML engineering agents running long-horizon tasks (12+ hour Kaggle competitions, multi-day model development) on infrastructure like serverless GPU clusters, FAVA Trails addresses three specific failure modes:

1. **Session persistence across context window resets.** When the context window fills and the agent needs to continue, FAVA Trails provides the full history of what was tried, what worked, what didn't, and why — reconstructable from versioned memory rather than lost when the window rolls over.

2. **Experiment branch isolation.** The agent can branch three parallel hypotheses (different model architectures, different feature engineering approaches) without cross-contamination. Each branch carries its own reasoning chain. The winning branch merges to main; the losing branches are atomically discarded.

3. **Preventing re-exploration of dead ends.** Supersession tracking means that when a hyperparameter search proves fruitless and is explicitly abandoned, future recall queries will not resurface that abandoned line of reasoning. The agent doesn't waste tokens re-discovering that "learning rate 0.1 diverges" if that was already established and marked as superseded.

### Can I use FAVA Trails as a drop-in replacement for my current memory backend?

Not as a semantic-RAG drop-in. Today's MCP `recall` is lexical substring-AND search over governed records, plus exact `get_thought` by ULID. A planned adapter that maps foreign `search()` APIs onto a future semantic index is **unreleased** and must not be assumed present. For frameworks with custom memory abstractions, the MCP interface is the integration point today.

### What about performance? My agent loop runs at millisecond timescales.

FAVA Trails distinguishes draft writes from promotion. The following numbers are **design targets only**, not published benchmarks, and they do **not** include a semantic index:

- **Draft save:** < 50ms target on local disk for the inner loop.
- **Lexical recall:** depends on corpus size (full scan of visibility-allowed markdown records in-process today).
- **Trust Gate evaluation:** uses the configured LLM; treat it as a promotion-path cost, not an inner-loop cost.

Publish hardware specs, dataset sizes, and concurrency conditions before treating any latency figure as a guarantee. The architecture still aims to keep draft writes off the governance path.

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

Each configured agent identity gets its own authoring view. Default governed `recall`/`get_thought` hide unapproved drafts by lifecycle status plus the process-configured author identity — not by cryptographic isolation between concurrent callers. Agents sharing one MCP endpoint share one identity boundary; direct filesystem access to the data repo remains operator-trusted. Coordination of *approved* work still happens through shared truth:

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

What holds today: the engine does not embed your corpus in its source, does not collect product telemetry, and does not require a FAVA-hosted cloud. The MCP server is effectively request-scoped for durable product state — your Fuel directory is separate and under your controls.

What does **not** hold by default: **Trust Gate can egress content.** With the shipped OpenRouter default, `propose_truth` sends the proposed record content and selected redacted metadata to that provider. Configure a local OpenAI-compatible endpoint, supply human-only approval, or otherwise disable LLM review when external egress is unacceptable (further local-only hardening is tracked in issue #101). Your corporate IP stays on your infrastructure only to the extent your Trust Gate provider and hosting choices keep it there.

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

**Shipped (current tree):** Versioned thought store with crash-proof persistence, governed/authoring/history visibility, Trust Gate / human approval provenance, supersession lineage, MCP integration, lexical `recall`, 1-hop relationship expansion, local Rich Views reader.

**In design / discovery (not shipped by this FAQ):** Continuous Pull Daemon automation; a dedicated search/retrieval layer after Lima Discovery ([issue #59](https://github.com/MachineWisdomAI/fava-trails/issues/59)) — candidates may include full-text indexes or, only if discovery proves need, derived semantic indexes. **No embeddings product, vector database, or retrieval architecture is selected in #59's discovery gate.**

**Later themes (aspirational):** richer temporal queries, redaction workflows, optional graph projections. Treat these as research directions until a commitment-class PRD exists.

### Is FAVA Trails open source?

FAVA Trails is developed by Machine Wisdom Solutions Inc. as an open-source project. The MCP server is a standalone Python package designed for integration with any MCP-compatible agent framework.

---

## The Competitive Landscape

### How does FAVA Trails compare to Beads/Dolt?

Steve Yegge's Beads system, now running on Dolt, demonstrated the 10× session duration improvement that validates the versioned memory thesis. Beads and FAVA Trails share the same foundational insight: agents need version-controlled structured data.

The key architectural difference: Beads uses SQL tables (Dolt) while FAVA Trails uses Markdown files with structured frontmatter. This reflects a design philosophy choice about cognitive ergonomics — LLMs are natively trained on and optimized for reading and writing Markdown, not managing SQL schemas and resolving row-level relational merges. Dolt provides versioned SQL primitives that *can* achieve gated merges and supersession through custom workflows, but these are application-layer concerns, not first-class primitives with built-in audit hooks and defaults. For orchestrating multi-agent swarms where work is rigidly defined as tickets, Dolt excels. For agents whose primary mode is reasoning in natural language, FAVA Trails's Markdown-native approach reduces cognitive overhead.

### How does FAVA Trails compare to Goodmem or other vector memory APIs?

Vector memory APIs (Goodmem, Mem0, Zep) optimize for semantic retrieval over embeddings. They are strong when the job is similarity RAG over relatively static text.

FAVA Trails optimizes for a different surface: governance, provenance, and state evolution — gated promotion, supersession lineage, visibility modes, and an auditable markdown+git substrate. Default `recall` today is lexical, not semantic. A derived full-text or vector index may appear later as a **rebuildable projection** if discovery (#59) justifies it; the versioned store remains the source of truth either way. These are complementary concerns, not a claim that FAVA already ships semantic search.

### How does FAVA Trails compare to Graphiti or other temporal knowledge graphs?

Graphiti provides relationship tracking and temporal awareness — capabilities that FAVA Trails's roadmap includes in Phase 4 (Temporal Knowledge Graph). The difference is architectural: Graphiti is a graph database that agents write to directly. FAVA Trails's graph layer is a *derived projection* from the versioned store.

This distinction matters for trust and governance. In FAVA Trails, the graph can be rebuilt from the versioned history at any time. Graph corruption doesn't mean data loss. And the Trust Gate governs what enters the versioned store — the graph inherits those governance guarantees.

For teams that need graph intelligence today, FAVA Trails's Phase 1 schema includes typed relationships in thought frontmatter that can be projected to Graphiti or Neo4j as a downstream consumer.
