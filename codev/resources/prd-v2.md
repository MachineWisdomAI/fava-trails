# Product Requirements Document: FAVA Trail

## Federated Agentic Versioned Audit Trail

**Version 2.0 | February 2026**
**Status:** Active — Supersedes Memcurial PRD v1.0 and FAVA Trail Technical Specification v1.0
**Owner:** Machine Wisdom Solutions Inc.

---

## Document Governance

This PRD defines **what** FAVA Trail must do. It deliberately abstracts away substrate selection (which version control system, which graph database, which vector store) because every technology choice involves tradeoffs documented in the companion *Architectural Choices of the FAVA Trail Agentic Memory Systems* comparison analysis. Implementation decisions are recorded as Architecture Decision Records (ADRs) in `memory/shared/decisions.md`.

**Companion documents:**

- *Architectural Choices: A Comparative Analysis* — Evaluates substrate tradeoffs across vector stores, structured SQL VCS, unstructured Markdown VCS, and native DAG systems.
- *FAVA Trail Technical Specification v1.0* — Current implementation architecture (JJ + MCP + SQLite).
- *SPIR Alignment Review* — Gap analysis between this PRD and the implementation plan.

---

## 1. Vision

FAVA Trail is a versioned memory system that makes AI agents remember reliably, correct themselves transparently, and coordinate with each other through shared ground truth. It treats versioned data persistence as a first-class architectural foundation rather than a bolted-on afterthought.

The strategic thesis: **similarity is not correctness**. Current agent memory systems optimize for semantic similarity (vector retrieval) when professional deployment demands semantic correctness (provenance-tracked, version-aware, auditable recall). FAVA Trail bridges this gap — what we term the **Correctness-Congruence Gap** — by ensuring that every memory carries its full lineage: what was believed, when it changed, why it changed, and who approved the change.

### The Correctness-Congruence Gap

Technical validation (Correctness) asks: *Is this fact schema-compliant and internally consistent?* This is a closed-world problem solvable through validation rules.

Intent alignment (Congruence) asks: *Is this fact consistent with the historical context, unstated constraints, and strategic direction established over months of prior work?* This is an open-world problem requiring temporal context that flat retrieval systems cannot provide.

FAVA Trail resolves this gap by making version history, relationship graphs, and provenance chains queryable — transforming agents from stateless responders into contextually grounded collaborators that operate as architects, not coders.

### Target Outcomes

- **10× agent session duration** — from ~1 hour (raw coding agents) to 12+ hours of productive, contextually coherent work.
- **Zero data loss on crash** — agent termination, context window exhaustion, or service restart must never destroy accumulated work.
- **Auditable decision provenance** — every memory state change traceable to its origin, rationale, and approval.

---

## 2. Problem Statement

Modern AI agents operate with a fundamental disability: they cannot reliably remember. This manifests across three documented failure modes.

### 2.1 Context Rot Degrades Performance at Scale

The Chroma Technical Report (July 2025) evaluated 18 leading LLMs and documented that model performance grows increasingly unreliable as input length grows, even on simple tasks. This is not a model capability limit — it is an architectural constraint. As context accumulates, contradictory facts co-exist and irrelevant information dilutes signal.

Current approaches compound the problem. Naive context accumulation stuffs everything into the prompt until the model degrades. RAG systems introduce semantic drift — the gap between what the user meant and what the vector embedding retrieved. Neither approach provides mechanisms for correction, rollback, or auditing what the agent "believed" at any point in time.

### 2.2 The Correctness-Congruence Gap Blocks Professional Deployment

In high-stakes professional services — legal, medical, financial, infrastructure — agents must not merely retrieve relevant information but retrieve the *correct* information with the *correct interpretation* as established by prior interactions. A versioned memory system preserves the full provenance chain that flat retrieval systems discard.

### 2.3 Single-Agent Sessions Are Catastrophically Short

Raw coding agent sessions max out at approximately one hour — not because of model limitations but because agents lose track of their own work. Without structured memory persistence, agents waste tokens re-discovering context, make contradictory decisions across turns, and eventually drift with no recovery mechanism.

### 2.4 Market Validation

The architectural pattern FAVA Trail implements is already proven in production by multiple independent teams converging on the same solution:

- **Beads** (Steve Yegge / Gas Town): Demonstrated 10× improvement in agent session duration through versioned structured data with schema-enforced relationships.
- **DoltHub**: Validated that the version control model of recall is already embedded in base LLM training — agents use branching, diffing, and rewinding effectively without additional prompting.
- **OpenAI Memory Architecture** (Agents SDK Cookbook, January 2026): Confirmed the global/session scoping pattern and the inject → reason → distill → consolidate lifecycle that FAVA Trail implements.

---

## 3. Product Pillars

FAVA Trail's requirements are organized into five pillars, each addressing a distinct failure mode in current agent memory systems. Requirements are prioritized P0 (must-have for MVP), P1 (must-have for production), or P2 (required for enterprise scale).

---

### Pillar 1: Versioned Persistence

*Agents must never lose work, and all memory state changes must be recoverable.*

#### REQ-1.1: Crash-Proof Persistence [P0]

Every memory write must be durably persisted before the write operation returns. If an agent process is killed, crashes, loses connectivity, or exhausts its context window, zero accumulated work is lost.

**Acceptance Criteria:**
- Automated chaos testing (random process termination) produces 0% data loss across 1,000 trials.
- No concept of "dirty" or "unsaved" state exists at the application layer.
- Recovery from crash requires zero manual intervention.

**Substrate Implication:** The versioning backend must persist state automatically and continuously, not on explicit save. Backends that maintain an in-memory dirty state between explicit commits do not satisfy this requirement.

#### REQ-1.2: Complete Audit Trail [P0]

Every memory state change must be recorded with: timestamp, actor identity (which agent or human), operation description, and a snapshot or diff of the affected state. The audit trail itself must be immutable — entries cannot be silently modified or deleted.

**Acceptance Criteria:**
- 100% of state changes appear in the audit log with full metadata.
- Given any point in time T, the system can reconstruct the exact memory state as it existed at T.
- Audit log is exportable in a format suitable for compliance review (SOC 2, ISO 27001).

**Substrate Implication:** The backend must provide native operation logging or commit history with metadata. Application-layer logging is acceptable only if it is tightly coupled to the persistence transaction (same atomic operation).

#### REQ-1.3: Deterministic State Reconstruction [P1]

Given a memory identifier and a point in time (or version reference), the system must return the exact content that existed at that state. This is not "similar content" — it is byte-identical reconstruction.

**Acceptance Criteria:**
- `recall(thought_id, at_version=V)` returns identical content regardless of subsequent mutations.
- Temporal queries ("what did we believe about X on January 15?") return precise historical state.

#### REQ-1.4: Localized Cascading Repair [P1]

When an error is discovered in a reasoning chain, the system must support surgical correction of the affected region without discarding the entire execution state. The correction must propagate to dependent memories while preserving unaffected work.

**Acceptance Criteria:**
- An incorrect memory in a chain of 10 dependent memories can be corrected, and only the directly affected downstream memories are flagged for review.
- Unrelated concurrent work is not disturbed by the repair operation.

**Substrate Implication:** The backend must support branching or equivalent isolation primitives that allow parallel state modification without mutual interference.

---

### Pillar 2: Draft Isolation and Governance

*Agent work-in-progress must be invisible to other agents until explicitly promoted through a validation gate.*

#### REQ-2.1: Persistent Draft Isolation [P0]

Each agent must operate in an isolated workspace where its in-progress reasoning is invisible to other agents reading shared truth. The draft workspace must be persistent (survive crashes), queryable by the owning agent, and independently discardable.

**Acceptance Criteria:**
- Agent A writes 50 draft memories over 3 days. Agent B, querying shared memory during this period, retrieves zero of Agent A's draft memories.
- Agent A can query its own draft memories at any time.
- If Agent A's investigation proves invalid, all 50 draft memories are discarded in a single atomic operation with zero residue in shared memory.

**Substrate Implication:** The backend must provide branch-like isolation where writes are scoped to a workspace and invisible to other workspaces until explicit promotion.

#### REQ-2.2: Trust Gate (Hallucination Filtering) [P0]

Memory promotion from draft to shared truth must pass through a validation gate. The Trust Gate evaluates proposed memories for factual consistency, schema compliance, and alignment with existing shared truth before allowing promotion.

**Acceptance Criteria:**
- No memory enters shared truth without Trust Gate evaluation.
- Trust Gate decisions (accept, reject, request revision) are logged with rationale.
- Trust Gate rejection does not destroy the proposed memory — it remains in draft for revision.
- Human override capability exists for both accepting rejected proposals and rejecting accepted proposals.
- Trust Gate supports configurable validation policies per namespace (more stringent for client-facing memories than for internal observations).

#### REQ-2.3: Atomic Bulk Discard [P0]

When an entire line of investigation proves invalid, the system must support instant, atomic discard of all related draft memories. "Atomic" means either all memories are discarded or none are — no partial cleanup state.

**Acceptance Criteria:**
- Discard of 100 draft memories completes in under 1 second.
- Post-discard, no traces of the discarded memories appear in any query (draft or shared).
- The discard operation itself is logged in the audit trail.

#### REQ-2.4: Promotion Workflow [P1]

The lifecycle of a memory follows a defined progression: **Draft → Proposed → Accepted → Shared Truth**. Each transition has defined gates and actors.

**Acceptance Criteria:**
- Draft: Visible only to the authoring agent. Mutable.
- Proposed: Submitted to the Trust Gate. Immutable pending review.
- Accepted: Passed Trust Gate validation. Visible to all agents.
- Rejected memories return to Draft status with reviewer feedback attached.

**Substrate Implication:** The backend must support phase-like state transitions, either natively (e.g., Mercurial's secret/draft/public phases) or through application-layer metadata on an immutable append-only store.

---

### Pillar 3: Cognitive Integrity

*The memory system must faithfully represent the messy reality of agent reasoning, including contradictions, corrections, and evolving beliefs.*

#### REQ-3.1: Conflict-Tolerant Storage [P0]

The system must be capable of storing contradictory beliefs without requiring immediate resolution. When two agents (or the same agent across sessions) hold mutually exclusive conclusions about the same topic, both conclusions must be persistable and retrievable as a structured conflict — not silently merged or discarded.

**Acceptance Criteria:**
- Two contradictory memories about the same entity can be committed simultaneously.
- The conflict is represented as structured data (not a merge error or blocked operation).
- A resolution workflow exists: a designated agent or human can review the conflict, select or synthesize a resolution, and the conflict artifact is preserved in history.

**Substrate Implication:** The backend must either support first-class conflict representation (e.g., algebraic tree conflicts) or the application layer must implement conflict detection and structured storage on a backend that permits concurrent writes.

#### REQ-3.2: Supersession Tracking [P0]

When a memory is corrected, updated, or invalidated, the old memory must be tombstoned — hidden from default retrieval but preserved in history. The tombstone must link the old memory to its successor with metadata explaining the reason for supersession. This prevents agents from re-deriving invalidated conclusions.

**Acceptance Criteria:**
- Default `recall` queries never return superseded memories.
- An explicit `include_superseded=True` parameter surfaces the full lineage for archaeological review.
- The supersession record includes: predecessor ID, successor ID, supersession reason, timestamp, actor.
- Bulk supersession (invalidating an entire reasoning chain) is supported.

**Substrate Implication:** The backend must either provide native obsolescence markers (e.g., Mercurial's hg-evolve) or the application layer must implement supersession tracking via metadata fields on immutable memory artifacts.

#### REQ-3.3: Persistent Identity [P0]

Every memory artifact must carry a unique identifier that remains stable across all mutations: amendments, rebases, branch merges, and storage compaction. The identifier must be independent of content hash and storage location.

**Acceptance Criteria:**
- A memory created on Branch A, amended twice, merged to main, and then further amended on main retains the same identifier throughout.
- External systems (graph databases, vector stores, audit logs) can reference a memory by its persistent ID with confidence that the reference remains valid indefinitely.

**Substrate Implication:** The backend must provide content-independent persistent identifiers (e.g., JJ's Change-IDs, application-layer ULIDs) rather than content-addressed hashes that change on every mutation.

#### REQ-3.4: Schema Enforcement [P0]

All memory artifacts must conform to a validated schema. Schema violations must be caught at write time, not at retrieval time. The schema must enforce structural requirements (required fields, type constraints) while permitting flexible content.

**Acceptance Criteria:**
- A memory write that violates the schema is rejected with a descriptive validation error before persistence.
- The schema is versioned — schema evolution does not invalidate existing memories.
- Schema includes at minimum: thought ID, thought type, creation timestamp, author, content body, relationships, namespace, and supersession fields.

#### REQ-3.5: Data Redaction [P1]

The system must provide a capability to permanently remove specific content (e.g., accidentally persisted secrets, PII) while maintaining graph integrity for remaining memories. Redaction must be propagable to all derived stores (vector indices, graph projections).

**Acceptance Criteria:**
- Redaction of a specific memory's content removes the content from all storage tiers (primary, vector index, graph projection) within a bounded time window.
- The memory's metadata skeleton (ID, relationships, timestamps) may be preserved with a "REDACTED" marker, or fully purged depending on configuration.
- Redaction events are logged in the audit trail.

---

### Pillar 4: Intelligence Layer

*Raw versioned storage becomes useful only when transformed into queryable intelligence — relationships, semantic retrieval, and episodic context.*

#### REQ-4.1: Typed Relationship Tracking [P0]

Memories must express explicit, typed relationships to other memories. Relationship types include at minimum: `DEPENDS_ON`, `REVISED_BY`, `AUTHORED_BY`, `CONTRADICTS`, `SUPERSEDES`, and `REFERENCES`. Relationships are first-class data, not inferred at query time.

**Acceptance Criteria:**
- Every memory can declare zero or more typed relationships to other memories via their persistent IDs.
- `recall(thought_id, include_relationships=True)` returns the memory and its 1-hop relationship graph.
- Relationship traversal adds less than 100ms latency over a non-relational recall.

**Substrate Implication:** Relationships may be stored as metadata within memory artifacts (frontmatter), in a sidecar graph store, or both. The primary versioned store must be the source of truth for relationship data; any graph database is a derived projection.

#### REQ-4.2: Semantic Retrieval [P1]

The system must support similarity-based retrieval ("find memories related to topic X") in addition to deterministic retrieval ("get memory with ID Y at version Z"). Semantic retrieval results must include provenance metadata (source version, freshness timestamp, confidence score).

**Acceptance Criteria:**
- Semantic queries return results within 500ms at p95.
- Each result includes: the matching memory, its version/timestamp, a freshness indicator, and the similarity score.
- The semantic index is a derived artifact — it can be rebuilt from scratch by replaying the versioned history. Semantic index corruption or drift does not affect the integrity of the primary store.

#### REQ-4.3: Temporal Knowledge Graph [P2]

The system must support hierarchical organization of memory history into episodes, communities, and thematic clusters. This graph layer enables agents to answer structural questions: "What sequence of decisions led to the current architecture?" or "Which project phase established the constraint we're working around?"

**Acceptance Criteria:**
- Entity extraction pipeline identifies Project, Decision, Plan, Client, and Constraint nodes from memory content.
- Typed edges connect entities across time (causal chains, dependency chains, revision chains).
- Community detection groups related memories into episodic summaries that provide global context without token overhead.
- Graph queries are available via the same MCP interface as direct memory operations.

**Substrate Implication:** The graph layer is explicitly separate from the versioned storage layer. It may be implemented as a property graph database (Neo4j, Graphiti), a lightweight SQLite graph, or an in-memory structure — the PRD does not prescribe the technology. The critical constraint is that the graph must be derivable from the versioned store (not an independent source of truth).

#### REQ-4.4: Incremental Processing Pipeline [P2]

Downstream processing (entity extraction, embedding generation, graph projection) must operate on incremental changes rather than full reprocessing. In environments with 1% daily churn, only the modified delta triggers downstream computation.

**Acceptance Criteria:**
- Change Data Capture (CDC) mechanism detects new, modified, and superseded memories.
- Downstream processors receive only the delta, not the full corpus.
- Full reprocessing from version history is available as a recovery mechanism but is not the normal operating mode.

---

### Pillar 5: Federation and Scale

*The system must support multiple agents coordinating through shared memory, with controls that prevent information overload and ensure appropriate access boundaries.*

#### REQ-5.1: Multi-Agent Synchronization [P1]

Multiple agents must be able to read and write to the same memory corpus concurrently. Each agent operates on its own isolated workspace (per REQ-2.1), with a synchronization mechanism that propagates accepted shared truth to all agents within a bounded latency window.

**Acceptance Criteria:**
- A memory accepted into shared truth becomes visible to all agents within 30 seconds.
- Concurrent writes by different agents to different topics do not block each other.
- Concurrent writes to the same topic are handled by the conflict resolution mechanism (REQ-3.1), not by locking or serialization.
- Synchronization failures are detected and surfaced to the affected agent rather than silently swallowed.

#### REQ-5.2: Namespace Separation [P0]

Different knowledge domains must be isolated into distinct namespaces. At minimum: client-specific knowledge, firm-wide standards, project-scoped context, and agent-private scratchpad. Namespace boundaries must be enforceable — an agent querying "client preferences" must not inadvertently receive "firm standards" unless explicitly requested.

**Acceptance Criteria:**
- `recall(scope="client/acme")` returns only memories in the Acme client namespace.
- Cross-namespace queries require explicit opt-in: `recall(scope=["client/acme", "firm/standards"])`.
- Namespace creation does not require schema changes — new namespaces are additive.
- Namespace-level access policies are configurable (which agents can read/write which namespaces).

#### REQ-5.3: Token-Optimized Context Delivery [P1]

The system must deliver right-sized context to agents rather than flooding the context window with everything. Retrieval operations must support scope filtering, relevance ranking, and relationship-bounded traversal (1-hop dependencies, not full graph).

**Acceptance Criteria:**
- `recall` supports filtering by: namespace, project, tags, time range, thought type, and relationship depth.
- The default retrieval mode returns summaries with the option to expand to full content on demand.
- Token budget parameter allows the caller to specify maximum context size; the system returns the most relevant memories within budget.

#### REQ-5.4: Human-in-the-Loop Feedback [P1]

Human feedback must be capturable as first-class memories that influence future agent behavior. The feedback loop follows: Trigger (agent observes correction) → Capture (structured preference extraction) → Persist (versioned, schema-validated) → Inject (retrieved in relevant future contexts).

**Acceptance Criteria:**
- A `learn_preference` operation captures human corrections as typed memories (preference, constraint, style rule).
- Preferences are additive — the system never overwrites the entire preference profile, only updates facts contradicted by new feedback.
- Captured preferences are retrievable by namespace and context, ensuring client-specific preferences don't contaminate firm-wide behavior.

#### REQ-5.5: Enterprise Federation [P2]

The system must scale from single-agent local deployment to multi-agent distributed deployment to cross-organizational federated knowledge sharing.

**Acceptance Criteria:**
- Stage 1 (Local): Single agent, local storage, sub-millisecond latency for working memory operations.
- Stage 2 (Team): Multiple agents, shared repository, synchronization within bounded latency (REQ-5.1).
- Stage 3 (Enterprise): Distributed storage, namespace-level access control, cross-team knowledge sharing with policy enforcement.
- Stage 4 (Federation): Cross-organizational knowledge exchange with cryptographic provenance verification and trust boundaries.

---

## 4. System Constraints

These non-functional requirements act as hard gates for any substrate and architecture choice. Agents operate at machine timescales; the memory system must not become a bottleneck in the cognitive loop.

### 4.1 Latency Budgets

| Operation Class | Target Latency | Rationale |
|-----------------|---------------|-----------|
| Working memory write (draft save) | < 50ms | Must not block the agent's reasoning loop |
| Working memory read (draft recall) | < 100ms | Agent context assembly is latency-sensitive |
| Shared truth read (recall) | < 500ms p95 | Includes semantic query + relationship traversal |
| Shared truth write (promotion) | < 5 seconds | Trust Gate evaluation is acceptable as async |
| Synchronization propagation | < 30 seconds | Eventual consistency is acceptable for shared truth |
| Bulk discard | < 1 second for 100 memories | Must be fast enough to not block the discarding agent |

### 4.2 Concurrency

The system must support simultaneous non-blocking writes to divergent branches of the same memory corpus. Agent A working on Project X and Agent B working on Project Y must never contend for locks, even when both are writing to the same repository.

### 4.3 Storage Efficiency

The system must handle sustained agent operation (thousands of memory writes per day per agent) without unbounded storage growth. Compaction, garbage collection, and archival policies must be automated and configurable.

### 4.4 Integration Surface

The primary integration surface is the **Model Context Protocol (MCP)**. All memory operations (save, recall, sync, promote, discard, learn) must be exposed as MCP tools callable by any MCP-compatible agent framework. The MCP interface must abstract all substrate-specific details — agents interact with memories as semantic objects, never with VCS commands, SQL queries, or file paths.

---

## 5. Substrate Capability Requirements

This section defines the capabilities any versioning backend must provide to satisfy the product requirements above. It does not prescribe a specific technology. The companion *Architectural Choices* document evaluates how current options (JJ/Jujutsu, Mercurial/hg-evolve, Dolt, Git, bitemporal databases) satisfy these capabilities with their respective tradeoffs.

| Capability | Required For | Description |
|------------|-------------|-------------|
| **Automatic persistence** | REQ-1.1 | State must be durably persisted without explicit save commands. No "dirty working copy" state. |
| **Immutable history** | REQ-1.2, REQ-1.3 | Past states must be preserved and reconstructable. History rewriting for redaction (REQ-3.5) must be an explicit, audited operation. |
| **Operation logging** | REQ-1.2 | Every state change must produce a log entry with actor, timestamp, and description. |
| **Branching / isolation** | REQ-2.1, REQ-1.4 | Independent workspaces must support concurrent modification without mutual visibility until explicit promotion. |
| **Conflict persistence** | REQ-3.1 | Contradictory concurrent writes must be representable as structured data, not as blocked operations or silent merges. |
| **Content-independent identity** | REQ-3.3 | Artifacts must carry identifiers stable across content mutations, branch operations, and storage compaction. |
| **Atomic operations** | REQ-2.3 | Multi-artifact operations (bulk discard, bulk promote) must be atomic — all-or-nothing. |
| **Metadata extensibility** | REQ-3.2, REQ-4.1 | Each artifact must support arbitrary structured metadata (supersession links, relationships, namespace, tags) without schema migration on the backend. |
| **Ecosystem portability** | REQ-5.5 | Data must be extractable to standard formats. Vendor lock-in to a single backend must be avoidable through a well-defined abstraction layer. |

---

## 6. Evaluation Framework

### 6.1 Technical Validation Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Technical Validation Rate** | ≥ 75% | Percentage of memory operations that are valid, schema-compliant, and successfully persisted |
| **Intent Alignment (Congruence)** | 72–76% | Human evaluation of whether retrieved memories match intended context (sample-based audit) |
| **Crash Recovery** | 0% data loss | Automated chaos testing: random process termination followed by state recovery validation |
| **Audit Completeness** | 100% | Every memory state change traceable to audit log entry with full metadata |

### 6.2 Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Agent Session Duration** | 10× baseline | Compare task completion time with/without FAVA Trail; target 12-hour productive sessions |
| **Sync Latency** | < 30 seconds | Time from Trust Gate approval to visibility in other agents |
| **Semantic Query Latency** | < 500ms p95 | End-to-end time for semantic recall including index lookup and content fetch |
| **Trust Gate Throughput** | > 100 proposals/minute | Sustained load testing of validation pipeline |

### 6.3 Quality Signal Metric

The merge gate must be opinionated about signal quality. The economic trade-offs favor discarding low-signal information over retaining everything — rediscovery costs are minimal compared to the compute expense of agent paralysis from information overload.

| Classification | Action | Rationale |
|---------------|--------|-----------|
| High signal (decisions, constraints, corrections) | Promote to shared truth | Critical for Congruence |
| Medium signal (observations, context) | Promote with lower confidence score | Useful but not essential |
| Low signal (routine logs, transient state) | Discard or archive | Retention cost exceeds value |

---

## 7. Phased Delivery

This PRD is honest about the gap between full vision and pragmatic MVP. The phased approach prioritizes demonstrable value at each stage.

### Phase 1: Versioned Thought Store (MVP)

**Goal:** Prove that versioned memory persistence meaningfully extends agent session duration and prevents hallucination propagation.

**Requirements addressed:** REQ-1.1, REQ-1.2, REQ-2.1, REQ-2.2, REQ-2.3, REQ-3.2, REQ-3.3, REQ-3.4, REQ-4.1 (schema-level only), REQ-5.2.

**What this delivers:** Crash-proof persistence, draft isolation, Trust Gate, supersession tracking, persistent identity, schema enforcement, namespace separation, and relationship metadata in thought frontmatter.

**What this defers:** Semantic retrieval, graph database, multi-agent sync, federation, incremental processing pipeline.

**Success criterion:** A single agent using FAVA Trail produces contextually coherent work across a 12-hour session with zero data loss on simulated crashes.

### Phase 2: Multi-Agent Coordination

**Goal:** Enable multiple agents to share memory with conflict resolution and human feedback capture.

**Requirements addressed:** REQ-2.4, REQ-3.1, REQ-4.1 (1-hop traversal), REQ-5.1, REQ-5.3, REQ-5.4.

**What this delivers:** Pull Daemon synchronization, conflict interception and structured resolution, 1-hop relationship traversal on recall, token-optimized context delivery, `learn_preference` HITL tool.

**Success criterion:** Two agents working on the same project produce non-contradictory outputs, with conflicts surfaced and resolved through the Trust Gate workflow.

### Phase 3: Semantic Intelligence

**Goal:** Transform versioned storage into queryable intelligence through semantic retrieval and lightweight graph projection.

**Requirements addressed:** REQ-1.3, REQ-1.4, REQ-3.5, REQ-4.2, REQ-4.4.

**What this delivers:** Semantic vector index (derived from versioned store), incremental index rebuild, temporal queries, data redaction, localized cascading repair.

**Success criterion:** Semantic recall returns relevant memories with < 500ms p95 latency, and the index is demonstrably rebuildable from version history alone.

### Phase 4: Enterprise Graph and Federation

**Goal:** Full Temporal Knowledge Graph and cross-organizational federation.

**Requirements addressed:** REQ-4.3, REQ-5.5.

**What this delivers:** Entity extraction pipeline, property graph projection, community detection, episodic summaries, distributed federation with cryptographic provenance.

**Success criterion:** Graph-augmented retrieval measurably improves Intent Alignment (Congruence) scores over semantic-only retrieval.

---

## 8. Risk Analysis

### Product Risks (Substrate-Agnostic)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agents don't use memory effectively even when available | Medium | Critical | Design MCP tools to match agent cognitive patterns (Markdown-native, just-in-time retrieval). Validate with production dogfooding before scaling. |
| Trust Gate becomes a bottleneck blocking agent flow | Medium | High | Async promotion (agent continues working in draft while Trust Gate evaluates). Configurable strictness per namespace. |
| Memory accumulation causes Context Rot despite versioning | Medium | Medium | Quality signal classification at write time. Aggressive archival of low-signal memories. Token budget enforcement on retrieval. |
| Schema evolution breaks backward compatibility | Low | High | Schema versioning from day one. Migration tooling included in Phase 1. |
| Graph layer (Phase 4) doesn't deliver measurable improvement over semantic search (Phase 3) | Medium | Medium | Phase 3 must be independently valuable. Graph layer is additive, not required for core functionality. |

### Substrate-Specific Risks

Substrate-specific risks (VCS maturity, ecosystem size, backend stability, hosting availability) are documented in the companion *Architectural Choices* analysis and the relevant ADR. The mitigation strategy for all substrate choices is the same: **the MCP abstraction layer must be thick enough to permit substrate migration without agent-facing API changes.** Agents interact with `save_thought`, `recall`, `sync`, and `propose_truth` — never with VCS commands directly.

---

## 9. Success Definition

In professional services, a "plausible" response is a liability. FAVA Trail succeeds when it transforms a Large Language Model from a stateless text generator into a reliable, version-aware collaborator that operates with the contextual depth of a principal engineer who has been on the project since day one.

The ultimate test is not technical validation rate or semantic recall latency. It is whether the humans working alongside FAVA-Trail-equipped agents trust the system's memory enough to rely on it for high-stakes decisions — and whether that trust is justified by the auditable provenance trail that backs every retrieved memory.

---

*This PRD is a living document. It will be revised as implementation experience reveals which requirements are correctly specified, which need refinement, and which new requirements emerge from production use.*
