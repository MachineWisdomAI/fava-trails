# SECOM Compression Hooks (WORM Pattern)

Extractive compression at promote time for information density, based on:

> Microsoft ICLR 2025 "On Memory Construction and Retrieval for Personalized Conversational Agents" (arXiv:2502.05589)
> Reference implementation: [microsoft/SeCom](https://github.com/microsoft/SeCom)

## WORM Architecture (Write-Once-Read-Many)

The paper applies compression per-query at recall time. FAVA Trails deviates: we compress once at **promote time** via the `before_propose` hook. Thoughts are written once but recalled many times by many agents -- amortizing compression cost from O(recalls x thoughts) to O(promotes).

The original verbose draft is preserved in JJ commit history (draft -> promoted commit chain).

## Quick Start

### Prerequisites
- FAVA Trails installed: `uv add fava-trails` (or `pip install fava-trails`)
- A working FAVA Trails configuration with at least one trail

### Option A: Module Reference (zero-friction, no copying)

Add to the `hooks:` section of your `config.yaml`:

```yaml
# config.yaml (at data repo root)
hooks:
  - module: fava_trails.protocols.secom
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config:
      compression_threshold_chars: 500
      verbosity_warn_chars: 1000
      target_compress_rate: 0.6
      compression_engine: heuristic
```

### Option B: Local Copy (for customization)

```bash
cp -r "$(python -c 'import fava_trails.protocols.secom as p; import os; print(os.path.dirname(p.__file__))')" ./my-hooks/secom/
```

Then in `config.yaml`:
```yaml
hooks:
  - path: ./my-hooks/secom/
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config:
      compression_threshold_chars: 500
      verbosity_warn_chars: 1000
      target_compress_rate: 0.6
      compression_engine: heuristic
```

### Where Is `config.yaml`?

`config.yaml` lives at the root of your FAVA Trails data repository:
- `$FAVA_TRAILS_DATA_REPO/config.yaml`
- Or `~/.fava-trails/config.yaml` (default)

## Config Contract

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `compression_threshold_chars` | `int` | `500` | Minimum content length to trigger compression in `before_propose` |
| `verbosity_warn_chars` | `int` | `1000` | Content length that triggers verbosity advisory in `before_save` |
| `target_compress_rate` | `float` | `0.6` | Target token retention rate (0.5-0.7 optimal per paper) |
| `compression_engine` | `str` | `"heuristic"` | `"heuristic"` (zero-dep) or `"llmlingua"` (production) |

## Compression Engines

| Engine | Dependency | Speed | Quality | Hallucination-free |
|--------|-----------|-------|---------|-------------------|
| `heuristic` | None | ~1ms | Sentence-level filtering | Yes |
| `llmlingua` | `llmlingua` PyPI | ~200-500ms CPU | Token-level extractive (paper's method) | Yes |

### Installing LLMLingua-2

```bash
uv add llmlingua
# or: pip install llmlingua
```

Then set `compression_engine: llmlingua` in config. Uses the `microsoft/llmlingua-2-xlm-roberta-large-meetingbank` model (355M params).

## Hooks

### `before_propose` -- Inline Compression

Compresses content via `Mutate(ThoughtPatch)` before promotion. Adds `secom-compressed` tag and compression metadata to `extra`. Skips if content is below threshold or already compressed. Fails open on errors.

### `before_save` -- Verbosity Advisor

Issues an `Advise` when saved content exceeds `verbosity_warn_chars`, suggesting front-loading key facts since extractive compression preserves tokens in order.

### `on_recall` -- Density-Aware Scoring

Boosts compressed thoughts proportionally to compression ratio via `RecallSelect`. The denoising effect of compression creates a wider similarity gap between relevant and irrelevant results.
