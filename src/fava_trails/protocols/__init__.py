"""FAVA Trails Context Engineering Protocol Reference Implementations.

Each protocol is a standalone hook module implementing a specific
context engineering pattern from the research literature:

- ace: Agentic Context Engineering (Curator Pattern) -- playbook-driven
  recall reranking and quality enforcement
- secom: SECOM Compression (WORM Pattern) -- extractive compression
  at promote time for information density
- rlm: RLM MapReduce (Orchestration Pattern) -- parallel mapper
  validation, progress tracking, and deterministic reducer retrieval

Protocols are composable. Each ships with a staggered default order
(ace=10, rlm=15, secom=20) so they execute in a defined sequence when
combined. Enable any combination via config.yaml hooks section.

Usage::

    # In config.yaml:
    hooks:
      - module: fava_trails.protocols.ace
        points: [on_startup, on_recall, before_save, after_save, after_supersede]

    # Or copy to project for customization:
    cp -r .../protocols/ace/ ./my-hooks/ace/
"""

PROTOCOLS = {
    "ace": "fava_trails.protocols.ace",
    "secom": "fava_trails.protocols.secom",
    "rlm": "fava_trails.protocols.rlm",
}
