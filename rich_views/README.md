# FAVA Rich Views Reader

This is a plain Astro static reader for FAVA source thought records.

Manual generation from fixture records:

```bash
cd rich_views
npm ci
uv run npm run generate:fixture
npm run build
```

Manual generation from a real FAVA data repo:

```bash
uv run fava-trails generate-reader \
  --source /path/to/fava-data-repo \
  --scope mwai/eng/fava-trails \
  --output rich_views
cd rich_views && npm run build
```

The generated site is a static snapshot. Each page includes the input scope and
generation time so readers can judge freshness. ULID thought IDs remain the
canonical route keys under `/thoughts/{thought_id}/`; derived titles are display
metadata only.
