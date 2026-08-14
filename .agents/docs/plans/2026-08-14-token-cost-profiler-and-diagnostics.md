---
status: completed
---

# Token Cost Profiler and Diagnostics Plan

Date: 2026-08-14

## Goal

Add smart diagnostics and cost profiling to `claude-tap`:
1. **Tool Payload Bloat Detector**: detect oversized tool results (>20KB or >50% context payload) with visual alerts in sidebar and detail trace.
2. **Cache Invalidation / Miss Diagnostics**: automatically attribute prompt cache misses (system prompt edited, tools changed, message history altered, TTL expired).
3. **Session Estimated Cost & Savings Calculator**: estimate token costs and cache savings based on model pricing across popular models (Claude, OpenAI, DeepSeek, Gemini).

## Scope

- In `claude_tap/viewer_assets/filters_search.js`:
  - Implement `MODEL_PRICING` lookup and `calculateEntryCost(entry)` / `calculateSessionCost(entries)`.
  - Calculate and display estimated cost (`#stat-cost`) and savings (`#stat-saved`) in top header stats.
- In `claude_tap/viewer_assets/diff.js` and `claude_tap/viewer_assets/detail_trace.js`:
  - Implement `diagnoseCacheInvalidation(curEntry, prevEntry)` to analyze cache creation causes.
  - Render diagnostic banner in detail trace when cache invalidation or miss is detected.
- In `claude_tap/viewer_assets/renderers.js` and `claude_tap/viewer_assets/sidebar.js`:
  - Implement `detectToolBloat(entry)` to identify high-token / large-payload tool results.
  - Display bloat badge in sidebar turns and alert banner in tool result blocks.
- In `claude_tap/viewer_assets/viewer.css`:
  - Add styles for cost badges, cache diagnostic card, tool bloat warning badges and banners.
- In `claude_tap/viewer_i18n.json`:
  - Add bilingual i18n keys for all 8 supported languages (`en`, `zh-CN`, `ja`, `ko`, `fr`, `ar`, `de`, `ru`).
- In `claude_tap/viewer.html`:
  - Add `#stat-cost-group` and `#stat-saved-group` containers in stats bar.

## Test Strategy

- JS Unit Tests:
  - Add tests in `tests/test_viewer_js_units.py` for cost calculation, cache diagnostics, and tool bloat detection.
- Browser Contracts & Visual Tests:
  - Update `tests/test_viewer_contracts.py` and `tests/test_viewer_i18n_source.py` to ensure complete coverage.
- Repo gate checks:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest tests/ -x --timeout=60`

## Success Criteria

- All unit tests and Playwright browser tests pass.
- All 8 languages in `viewer_i18n.json` have 100% key parity.
- Existing features, compact bundle loading, lazy loading, and diff workflows remain 100% backward compatible.
