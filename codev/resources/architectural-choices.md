# **Architectural choices of the FAVA Trail Agentic Memory Systems** 

## *A Comparative Analysis*

**Objective:** To define the optimal memory substrate for autonomous AI agents, evaluating current commercial APIs, structured version control, unstructured version control, and the theoretical ideal of natively evolved Directed Acyclic Graphs (DAGs).

The core challenge in agentic memory is no longer storage capacity; it is **state management, temporal lineage, and conflict resolution**. As agents execute long-horizon reasoning, they require a memory system that prevents "contextual flattening" (where contradictory past and present facts co-exist) while allowing for safe, isolated hypothesis testing.

## ---

**1\. Vector Search APIs (Goodmem) vs. Temporal Knowledge Graphs (Graphiti)**

The baseline approach to agent memory relies on semantic similarity, but this breaks down under the weight of continuous agent iteration.

### **Goodmem (Commercial Vector API)**

Goodmem provides a highly polished, managed service with native MCP tools and direct integration into frameworks like the Agent Development Kit (ADK).

* **The Appeal:** Zero-friction deployment. Ideal for simple Retrieval-Augmented Generation (RAG) where the agent only needs to look up static documentation.  
* **The Flaw ("Contextual Flattening"):** Vector databases are inherently flat. If an agent writes a flawed hypothesis (Thought A), and later corrects it (Thought A'), a vector search for the topic will retrieve *both* because they are semantically identical. Furthermore, as a closed-source commercial API, it violates local-first, zero-latency execution requirements.

### **Graphiti (Temporal Knowledge Graph)**

* **The Appeal:** Maps the explicit relationships between entities over time. When an agent updates a belief, the graph understands that the new node supersedes the old one, preventing the agent from retrieving stale hallucinations.

* **The Verdict:** While vector search (Goodmem) is insufficient for reasoning agents, a pure Knowledge Graph requires heavy LLM ingestion pipelines. The ideal architecture uses a lightweight, local vector/graph hybrid (e.g., SQLite \+ vector extension) acting purely as a *derivative index* of a version-controlled source of truth.

## ---

**2\. Versioned Memory: Structured (Dolt) vs. Unstructured (Jujutsu)**

Recognizing that agents need version control to survive crashes and manage state, the next architectural branch is between structured data and unstructured text.

### **Dolt / "Beads" (Structured SQL Version Control)**

Steve Yegge’s *Beads* system migrated to Dolt, a version-controlled SQL database, to manage multi-agent coordination.

* **The Appeal:** Brings Git-like branching to structured tables. Excellent for orchestrating multi-agent swarms where work is rigidly defined as tickets (e.g., SELECT \* FROM tasks WHERE status='blocked').  
* **The Flaw (Cognitive Ergonomics):** LLMs are natively trained on and optimized for reading and writing unstructured Markdown, not managing SQL schemas and resolving row-level relational merges. Forcing an agent's internal monologue into a SQL table creates unnecessary cognitive overhead.

### **FAVA Trail / Jujutsu (Unstructured Markdown Version Control)**

FAVA Trail wraps standard Markdown files in Jujutsu (JJ), a Git-compatible VCS.

* **The Appeal:** Agents "think" in their native tongue (Markdown), while the MCP server transparently handles complex versioning. JJ’s "working copy as commit" paradigm ensures crash-proof persistence—if an agent hangs, the thought is already checkpointed.  
* **Conflict as Data:** Unlike Dolt, which requires explicit row-merge resolutions, JJ materializes conflicts as tree algebra (A+(C-B)+(E-D)) directly in the file. This enables "cognitive dissonance": agents can commit contradictory beliefs, leaving the conflict materialized as a persistent artifact for a Critic Agent to resolve later.  
* **The Verdict:** FAVA Trail (JJ \+ Markdown) occupies the pragmatic sweet spot. It provides indestructible version control over the files agents naturally write, while remaining entirely portable via its colocated Git backend.

## ---

**3\. The Pragmatic Reality vs. The Purist Ideal**

FAVA Trail using JJ is the designated production path because of its high velocity and Git ecosystem compatibility. However, taking a rigorous look at the foundational **Memcurial** specification reveals what is lost in the compromise, framing a "North Star" for future architectural iterations.

### **The FAVA Trail / JJ Compromise**

JJ snapshots the *entire logical tree* of the working copy. It tracks state changes immaculately via stable Change-IDs, but it tracks *that* a state changed, not necessarily the semantic evolution of the thought itself. To build a Temporal Knowledge Graph on top of JJ, we are forced to engineer explicit schema workarounds (like the superseded\_by metadata field) to manually bridge the gap between file snapshots.

### **Future Work: The Memcurial \+ hg-evolve Purist Architecture**

The original Memcurial concept relies on Mercurial’s DAG and the hg-evolve extension. If the friction of Mercurial hosting (the lack of a modern, ubiquitous "GitHub for Hg") and repository management can be abstracted or managed cost-effectively, this represents the purest model for artificial cognition.

**Why hg-evolve is the Cognitive Ideal:**

1. **Native Obsolescence Tracking:** When an agent realizes a line of reasoning is a hallucination or dead end, evolve doesn't just rewrite history or create a new snapshot. It creates a native **obsolescence marker**. The DAG explicitly links the old, flawed thought to the new, corrected thought at the VCS kernel level. The system inherently understands: *Thought A was superseded by Thought A' because of X.*  
2. **Built-In Cognitive Phases:** Mercurial possesses a native phase system (secret, draft, public). This maps flawlessly to agentic workflows:  
   * **Secret:** The agent's isolated internal scratchpad.  
   * **Draft:** The formulated plan, ready for a Critic Agent's review.  
   * **Public:** The immutable ground truth merged into the shared corporate brain.  
     This governance workflow is enforced by the VCS itself, making it structurally impossible for an agent to accidentally leak a secret hallucination into public memory.  
3. **Delta-First Storage (Revlog):** Mercurial stores data as append-only, compressed deltas. For an agent making thousands of micro-edits to a contextual markdown file, appending tiny diffs is conceptually lighter and highly optimized compared to Git/JJ's object database, which creates a full blob snapshot for every micro-mutation.

### **Conclusion**

Building the production prototype on **FAVA Trail (JJ \+ SQLite)** is the correct strategic maneuver. It delivers crash-proof, conflict-tolerant, local-first memory using ubiquitous Git-compatible infrastructure.

However, the **Memcurial (hg-evolve)** architecture remains the theoretically perfect model. Should specialized AI infrastructure providers emerge that offer managed Mercurial endpoints without exorbitant operational overhead, migrating the memory substrate to a native obsolescence DAG would eliminate the need for manual graph-schema enforcement, allowing the version control system itself to act as the ultimate, self-curating brain.
---

## CLI Layer (Spec 14)

The FAVA Trails package now exposes two entry points:
- `fava-trails-server` — MCP server (agent-facing)
- `fava-trails` — CLI (human-facing setup and scope management)

Both share `src/fava_trails/` and reuse `config.py` helpers (`get_data_repo_root`, `sanitize_scope_path`, `get_trails_dir`).

### Scope Configuration Pattern
Two-file pattern for scope discovery:
1. `.fava-trails.yaml` — committed project default (`scope: mw/eng/project`)
2. `.env` — local gitignored override (`FAVA_TRAILS_SCOPE=mw/eng/project`)

`fava-trails init` populates `.env` from `.fava-trails.yaml`, closing the gap where agents skip file reads but reliably auto-load `.env`.

### .env Write Safety
`_update_env_file()` in `cli.py`:
- Parses line-by-line, preserving comments and blank lines
- Deduplicates repeated keys
- Atomic write: `tmp.write_text(...); tmp.replace(env_path)`
- Uses `with_name(name + ".tmp")` not `with_suffix(".tmp")` (dotfile safety)
