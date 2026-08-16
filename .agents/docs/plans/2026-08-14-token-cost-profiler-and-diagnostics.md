---
status: completed
---

# Token Cost Profiler and Tool Bloat Detector Plan

Date: 2026-08-14

## Goal

Add cost profiling and payload-bloat detection to the `claude-tap` viewer:

1. **Session Estimated Cost & Savings Calculator**: estimate per-turn and session
   token cost from a model pricing table, and show how much prompt caching saved
   against an uncached baseline.
2. **Tool Payload Bloat Detector**: flag individual `tool_result` blocks large
   enough to be worth a reader's attention, in both the sidebar and the detail
   trace.

Cache-miss attribution was originally part of this plan. It reads the prompt hash
chain rather than the token counts, which is a separate concern with its own
failure modes, so it ships as its own change (`diff.js`,
`diagnoseCacheInvalidation`) and is not covered here.

## Scope

- In `claude_tap/viewer_assets/filters_search.js`:
  - `MODEL_PRICING_TABLE` with `getModelPricing(model)` and
    `calculateEntryCost(entry)`; sum both into `#stat-cost` and `#stat-saved`
    inside `applyFilter`.
  - Anthropic cache rates are derived from each model's input rate via the
    published multipliers (read 0.1x, 5-minute write 1.25x) rather than
    transcribed per model, so a repricing touches one number.
  - `PRICING_AS_OF` records when the rates were last checked, and is shown to the
    reader so a stale figure is visibly stale.
- In `claude_tap/viewer_assets/renderers.js` and `claude_tap/viewer_assets/sidebar.js`:
  - `toolResultBloatInfo(block)` as the single size test, with
    `detectEntryToolBloat(entry)` built on it.
  - `TOOL_BLOAT_MIN_CHARS` is set from a measured distribution of tool results
    across real local sessions rather than picked by feel: the sizes are heavily
    right-skewed, so the threshold sits far out on the tail and flags only the
    handful of results large enough to dominate a turn.
  - Bloat badge on sidebar turns, alert banner on the offending tool result.
- In `claude_tap/viewer_assets/viewer.css`: styles for the cost stat, the sidebar
  bloat badge, and the tool bloat banner.
- In `claude_tap/viewer_i18n.json`: keys for all 8 supported languages
  (`en`, `zh-CN`, `ja`, `ko`, `fr`, `ar`, `de`, `ru`).
- In `claude_tap/viewer.html`: `#stat-cost-group` and `#stat-saved-group` in the
  stats bar.

## Known limitations

- Rates are hardcoded list prices and will drift as vendors reprice. The figure is
  labelled an estimate and carries `PRICING_AS_OF`, so a reader can judge it.
  A prior attempt at cost estimation was removed in v0.1.5 for exactly this
  maintenance cost (see `CHANGELOG.md`); the dated, single-source-of-truth table
  is the response to that.
- Traces report cache creation as one `cache_creation_input_tokens` count with no
  TTL breakdown, so every write is priced at the 5-minute rate. Sessions using
  1-hour caching are under-estimated on cache-populating turns.
- `CHARS_PER_TOKEN` is a coarse 4:1 approximation, used only to put a bloat
  warning in token terms.

## Test Strategy

- JS unit tests in `tests/test_viewer_js_units.py`: pricing resolution for the
  models actually in use, the cache-multiplier invariant, cost and savings
  arithmetic, the mixed priced/unpriced session disclosure, and the bloat
  threshold boundary.
- Browser contracts in `tests/test_viewer_contracts.py`: cost and saved stats
  render with provenance, bloat badge and banner appear on the oversized turn and
  not on the ordinary one.
- Repo gate checks:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest tests/ -x --timeout=60`

## Success Criteria

- Cost renders for current Claude models (the earlier table matched none of them).
- All 8 languages in `viewer_i18n.json` have 100% key parity.
- Existing features, compact bundle loading, lazy loading, and diff workflows
  remain backward compatible.
