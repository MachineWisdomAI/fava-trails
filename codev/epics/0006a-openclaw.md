# 0006a: OpenClaw Integration

**Status:** planned

OpenClaw memory plugin — TypeScript npm package that claims the `plugins.slots.memory` slot and bridges to FAVA Trails' MCP server over stdio. Provides lifecycle hooks (auto-recall, auto-capture), subprocess supervision, and scope-based write guardrails.

**Prerequisites:** Epic 0004a (rebrand), Spec 6 (Recall Enhancements), Spec 7 (Semantic Recall)

**Integration contract:** The plugin communicates with FAVA Trails exclusively via MCP over stdio. No direct access to the data repo or JJ backend. The plugin is a separate npm package (`openclaw-fava-trails`) in its own repo — it depends on the FAVA Trails CLI/server being installed but does not embed or fork it.

## Specs

- [ ] Spec 11: OpenClaw Memory Plugin
