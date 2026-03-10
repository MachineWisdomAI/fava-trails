# SECOM Compression Hooks (WORM Pattern)

Extractive token-level compression at promote time for information density, based on:

> Tsinghua University and Microsoft, ICLR 2025 "On Memory Construction and Retrieval for Personalized Conversational Agents" (arXiv:2502.05589)
> Reference implementation: [microsoft/SeCom](https://github.com/microsoft/SeCom)

## WORM Architecture (Write-Once-Read-Many)

The paper applies compression per-query at recall time. FAVA Trails deviates: we compress once at **promote time** via the `before_propose` hook. Thoughts are written once but recalled many times by many agents -- amortizing compression cost from O(recalls x thoughts) to O(promotes).

The original verbose draft is preserved in JJ commit history (draft -> promoted commit chain).

## Quick Start

### Prerequisites
- FAVA Trails installed: `uv add fava-trails` (or `pip install fava-trails`)
- LLMLingua-2 installed: `uv add fava-trails[secom]` (or `pip install fava-trails[secom]`)
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
      compression_engine:
        type: llmlingua
        model_name: microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank
        device_map: cpu
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
      compression_engine:
        type: llmlingua
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
| `compression_engine` | `str` or `dict` | see below | Compression engine configuration |

### `compression_engine` Config

Can be a string shorthand (`"llmlingua"`) or a full dict:

```yaml
compression_engine:
  # Required
  type: llmlingua              # Engine type (only "llmlingua" supported)

  # PromptCompressor constructor args (all optional, shown with defaults)
  model_name: microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank
  device_map: cpu              # "cpu", "cuda", "cuda:0", etc.
  use_llmlingua2: true
  model_config: {}             # Extra HuggingFace model config
  llmlingua2_config: {}        # LLMLingua-2 specific config

  # Per-call compress_prompt() defaults (all optional)
  compress_args:
    force_tokens: ["\n", ".", "?", "!", ",", "#", "-", "*"]
    force_reserve_digit: false
    drop_consecutive: false
    use_context_level_filter: false
    use_token_level_filter: true
    chunk_end_tokens: [".", "\n"]
    target_token: -1           # Override rate with absolute token count
```

Unknown engine types fail loudly at configure time. See the [LLMLingua docs](https://github.com/microsoft/LLMLingua) for the full list of `PromptCompressor` constructor and `compress_prompt` parameters.

## Compression Engine: LLMLingua-2

Uses **extractive token-level compression**. For each token, the model predicts keep/discard. Key properties:

- **Purely extractive**: Only original tokens survive. No paraphrasing, no rewriting, no new tokens generated.
- **Preserves named entities and identifiers**: Token-level decisions maintain factual anchors.
- **Optimal rate**: tau = 0.5-0.7 (retain 50-70% of tokens). Below 0.5, critical information loss.

### Available Models

| Model | Params | Disk | CPU Speed | Use Case |
|-------|--------|------|-----------|----------|
| `bert-base-multilingual-cased-meetingbank` | 178M | ~700MB | ~100-200ms | **Default** -- fast, good for CPU/laptop |
| `xlm-roberta-large-meetingbank` | 560M | ~2.2GB | ~400-800ms | Higher quality, needs more RAM/GPU |

Both are prefixed with `microsoft/llmlingua-2-`. Override via `compression_engine.model_name`. See the [LLMLingua repo](https://github.com/microsoft/LLMLingua) for the full set of supported models.

Install with:
```bash
pip install fava-trails[secom]
# or: uv add fava-trails[secom]
```

## Structured Data

SECOM's token-level compression has no notion of syntactic validity — JSON objects, YAML blocks, and fenced code blocks may be silently destroyed at promote time.

### Opt Out with `secom-skip`

Tag any thought with `secom-skip` to bypass compression entirely:

```python
save_thought(
    trail_name="my/scope",
    content='{"phases": ["build", "test"]}',
    metadata={"tags": ["secom-skip"]},
)
```

`secom-skip` means "do not compress this." It is semantically distinct from `secom-compressed` (which means "already compressed").

### Advisory on Save

When `before_save` detects structured content (fenced code blocks or JSON-like lines) and `secom-skip` is absent, it issues an `Advise` action with code `secom_structured_data_advisory`, suggesting you add the tag before promoting.

### Operator Warning on Compress

If compression proceeds on content that appears structured, `before_propose` logs a `WARNING` so operators can investigate unexpected data corruption.

## Hooks

### `before_propose` -- Inline Compression

Compresses content via `Mutate(ThoughtPatch)` before promotion. Adds `secom-compressed` tag and compression metadata to `extra`. Skips if content is below threshold, already tagged `secom-compressed`, or explicitly tagged `secom-skip`. Logs a `WARNING` when compressing content with detected structured data. Fails open on errors.

### `before_save` -- Verbosity Advisor

Issues `Advise` actions when:
- Saved content exceeds `verbosity_warn_chars` (code: `secom_verbosity_advisory`) — suggests front-loading key facts
- Content contains structured data (JSON/YAML/code blocks) and `secom-skip` is absent (code: `secom_structured_data_advisory`) — suggests adding the `secom-skip` tag

### `on_recall` -- Density-Aware Scoring

Boosts compressed thoughts proportionally to compression ratio via `RecallSelect`. The denoising effect of compression creates a wider similarity gap between relevant and irrelevant results.
