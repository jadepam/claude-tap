from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_tap import pricing
from claude_tap.pricing import LONG_CONTEXT_THRESHOLD, entry_cost, resolve_rates
from claude_tap.usage import normalize_usage

SONNET_4 = "claude-sonnet-4-20250514"
OPUS_4_1 = "claude-opus-4-1"


@pytest.fixture(autouse=True)
def _clear_price_cache():
    pricing._price_table.cache_clear()
    yield
    pricing._price_table.cache_clear()


def test_price_table_ships_with_provenance() -> None:
    meta = pricing.pricing_metadata()

    assert meta["source_url"].startswith("https://raw.githubusercontent.com/BerriAI/litellm/")
    assert meta["as_of"]
    assert meta["model_count"] > 100


def test_corrupt_price_file_degrades_to_no_cost(tmp_path: Path, monkeypatch) -> None:
    broken = tmp_path / "model_prices.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(pricing, "PRICES_PATH", broken)
    pricing._price_table.cache_clear()

    assert resolve_rates(SONNET_4) is None
    assert entry_cost(SONNET_4, {"input_tokens": 100, "output_tokens": 10}) is None
    assert pricing.pricing_metadata()["model_count"] == 0


def test_missing_price_file_degrades_to_no_cost(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pricing, "PRICES_PATH", tmp_path / "absent.json")
    pricing._price_table.cache_clear()

    assert resolve_rates(SONNET_4) is None


def test_unpriced_model_returns_none() -> None:
    assert entry_cost("totally-made-up-model", {"input_tokens": 10, "output_tokens": 1}) is None


def test_empty_usage_returns_none() -> None:
    assert entry_cost(SONNET_4, None) is None
    assert entry_cost(SONNET_4, "not a dict") is None  # type: ignore[arg-type]
    assert entry_cost(SONNET_4, {}) is None
    assert entry_cost(SONNET_4, {"input_tokens": 0, "output_tokens": 0}) is None


def test_bedrock_and_gateway_prefixes_resolve_to_the_same_rates() -> None:
    base = resolve_rates(SONNET_4)
    assert base is not None

    for alias in (
        "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "bedrock/anthropic.claude-sonnet-4-20250514-v1:0",
        "openrouter/anthropic/claude-sonnet-4-20250514",
    ):
        rates = resolve_rates(alias)
        assert rates is not None, alias
        assert (rates.input, rates.output, rates.cache_read) == (
            base.input,
            base.output,
            base.cache_read,
        ), alias


def test_long_context_tier_applies_above_200k() -> None:
    small = resolve_rates(SONNET_4, prompt_tokens=LONG_CONTEXT_THRESHOLD)
    large = resolve_rates(SONNET_4, prompt_tokens=LONG_CONTEXT_THRESHOLD + 1)
    assert small is not None and large is not None

    assert small.long_context is False
    assert large.long_context is True
    # Sonnet 4 doubles input and lifts output above the 200K boundary.
    assert large.input == pytest.approx(small.input * 2)
    assert large.output > small.output
    assert large.cache_read > small.cache_read
    assert large.cache_write > small.cache_write


def test_long_context_tier_is_not_invented_for_models_without_one() -> None:
    """Opus 4.1 caps at 200K input, so a huge prompt must not tier its rates up."""
    base = resolve_rates(OPUS_4_1)
    huge = resolve_rates(OPUS_4_1, prompt_tokens=900_000)
    assert base is not None and huge is not None

    assert huge.long_context is False
    assert huge.input == base.input
    assert huge.output == base.output


def test_long_context_cost_uses_tiered_rates() -> None:
    usage = {"input_tokens": 300_000, "output_tokens": 1_000}

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.long_context is True
    assert priced.cost == pytest.approx(300_000 * 6e-06 + 1_000 * 2.25e-05)


def test_cache_write_ttl_uses_the_one_hour_rate() -> None:
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 10_000, "output_tokens": 5}

    default_ttl = entry_cost(SONNET_4, usage)
    one_hour = entry_cost(SONNET_4, usage, cache_ttl_1h=True)
    assert default_ttl is not None and one_hour is not None

    assert default_ttl.cost == pytest.approx(100 * 3e-06 + 10_000 * 3.75e-06 + 5 * 1.5e-05)
    assert one_hour.cost == pytest.approx(100 * 3e-06 + 10_000 * 6e-06 + 5 * 1.5e-05)
    assert one_hour.cost > default_ttl.cost


def test_one_hour_rate_is_ignored_when_the_model_has_no_such_tier() -> None:
    """gemini-2.5-pro has no *_above_1hr field; asking for 1h must not change rates."""
    rates = resolve_rates("gemini-2.5-pro", cache_ttl_1h=True)
    base = resolve_rates("gemini-2.5-pro")
    assert rates is not None and base is not None

    assert rates.cache_write == base.cache_write


def test_separate_cache_bucket_is_billed_on_top_of_input() -> None:
    """Anthropic reports cache reads outside input_tokens, so both are billed."""
    usage = normalize_usage(
        {
            "input_tokens": 1_000,
            "cache_read_input_tokens": 50_000,
            "output_tokens": 100,
        }
    )
    assert usage["cache_read_in_input"] is False

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.cost == pytest.approx(1_000 * 3e-06 + 50_000 * 3e-07 + 100 * 1.5e-05)
    assert priced.uncached_cost == pytest.approx(51_000 * 3e-06 + 100 * 1.5e-05)
    assert priced.saved == pytest.approx(priced.uncached_cost - priced.cost)


def test_bedrock_camel_case_cache_bucket_is_also_separate() -> None:
    usage = normalize_usage(
        {
            "inputTokens": 1_000,
            "cacheReadInputTokens": 50_000,
            "outputTokens": 100,
        }
    )
    assert usage["cache_read_in_input"] is False

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.cost == pytest.approx(1_000 * 3e-06 + 50_000 * 3e-07 + 100 * 1.5e-05)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(
            {"input_tokens": 51_000, "cached_tokens": 50_000, "output_tokens": 100},
            id="responses_cached_tokens",
        ),
        pytest.param(
            {
                "input_tokens": 51_000,
                "input_tokens_details": {"cached_tokens": 50_000},
                "output_tokens": 100,
            },
            id="input_tokens_details",
        ),
        pytest.param(
            {
                "prompt_tokens": 51_000,
                "prompt_tokens_details": {"cached_tokens": 50_000},
                "completion_tokens": 100,
            },
            id="prompt_tokens_details",
        ),
        pytest.param(
            {
                "promptTokenCount": 51_000,
                "cachedContentTokenCount": 50_000,
                "candidatesTokenCount": 100,
            },
            id="gemini_cached_content",
        ),
    ],
)
def test_embedded_cache_tokens_are_not_billed_twice(raw: dict[str, object]) -> None:
    """OpenAI- and Gemini-shaped usage counts cached tokens inside the prompt total.

    Billing the reported input as-is would charge those 50K tokens at the full
    input rate and again at the cache-read rate.
    """
    usage = normalize_usage(raw)
    assert usage["cache_read_in_input"] is True
    assert usage["cache_read_input_tokens"] == 50_000

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    # 1K fresh input, 50K read from cache — not 51K fresh plus 50K cached.
    assert priced.cost == pytest.approx(1_000 * 3e-06 + 50_000 * 3e-07 + 100 * 1.5e-05)
    assert priced.uncached_cost == pytest.approx(51_000 * 3e-06 + 100 * 1.5e-05)


def test_embedded_cache_read_larger_than_input_clamps_to_zero_fresh_input() -> None:
    usage = {"input_tokens": 100, "cache_read_input_tokens": 500, "cache_read_in_input": True}

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.cost == pytest.approx(500 * 3e-07)


def test_embedded_cache_read_counts_toward_the_long_context_tier() -> None:
    """The tier follows prompt size, not the share billed at the uncached rate."""
    usage = {
        "input_tokens": 300_000,
        "cache_read_input_tokens": 299_000,
        "cache_read_in_input": True,
    }

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.long_context is True
    assert priced.cost == pytest.approx(1_000 * 6e-06 + 299_000 * 6e-07)


def test_saved_stays_signed_for_a_write_only_turn() -> None:
    """A 5-minute cache write costs 1.25x uncached input, so writing loses money."""
    usage = {"input_tokens": 0, "cache_creation_input_tokens": 100_000, "output_tokens": 10}

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.cost > priced.uncached_cost
    assert priced.saved < 0


def test_negative_and_non_numeric_token_counts_are_ignored() -> None:
    usage = {
        "input_tokens": -5,
        "cache_read_input_tokens": "many",
        "cache_creation_input_tokens": True,
        "output_tokens": 10,
    }

    priced = entry_cost(SONNET_4, usage)
    assert priced is not None
    assert priced.cost == pytest.approx(10 * 1.5e-05)


def test_model_from_path_matches_gemini_style_urls() -> None:
    assert pricing.model_from_path("/v1beta/models/gemini-2.5-pro:generateContent") == "gemini-2.5-pro"
    assert pricing.model_from_path("/v1/messages") == ""
    assert pricing.model_from_path(None) == ""  # type: ignore[arg-type]


def test_vendored_table_only_carries_the_fields_the_adapter_reads() -> None:
    payload = json.loads(pricing.PRICES_PATH.read_text(encoding="utf-8"))
    allowed = {
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_read_input_token_cost",
        "cache_creation_input_token_cost",
        "cache_creation_input_token_cost_above_1hr",
        "input_cost_per_token_above_200k_tokens",
        "output_cost_per_token_above_200k_tokens",
        "cache_read_input_token_cost_above_200k_tokens",
        "cache_creation_input_token_cost_above_200k_tokens",
        "max_input_tokens",
        "litellm_provider",
    }

    extra = {field for entry in payload["models"].values() for field in entry} - allowed
    assert extra == set()
