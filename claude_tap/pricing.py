"""Model pricing adapter over a vendored LiteLLM price table.

This module is the single owner of price data and cost arithmetic. The viewer
receives numbers it only has to format; nothing downstream re-derives a rate.

Three details the previous JavaScript implementation got wrong and this module
handles explicitly:

* **Long-context tiers.** Anthropic and Google bill input above 200K tokens at a
  higher rate. LiteLLM carries those as ``*_above_200k_tokens`` fields, and they
  are per-model: ``claude-sonnet-4-20250514`` has them, ``claude-opus-4-1`` (a
  200K-max model) does not.
* **Cache write TTL.** A 1-hour cache write costs more than the default 5-minute
  one (``cache_creation_input_token_cost_above_1hr``).
* **Where cached tokens are counted.** Anthropic reports cache reads in a bucket
  separate from ``input_tokens``; OpenAI-shaped gateways report them inside it.
  Billing the embedded case without subtracting first charges those tokens twice.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

PRICES_PATH = Path(__file__).parent / "model_prices.json"

# The tier boundary LiteLLM encodes in its *_above_200k_tokens field names.
LONG_CONTEXT_THRESHOLD = 200_000

_MODEL_FROM_PATH_RE = re.compile(r"/models?/([^:?/]+)")
# Bedrock and Vertex prefix the region or publisher onto the model id.
_STRIP_PREFIX_RE = re.compile(
    r"^(?:bedrock/|openrouter/|azure_ai/|azure/|vertex_ai/|"
    r"(?:us|eu|apac|au|jp|ca|global)\.)+",
    re.IGNORECASE,
)


class ModelRates(NamedTuple):
    """Per-token rates for one model, already resolved for the request size.

    A rate is ``None`` when the price table has no figure for that bucket, which
    is different from a rate of ``0.0``. Several entries genuinely lack cache
    pricing (``gpt-4o`` and ``gemini-2.5-pro`` carry no cache-creation cost), and
    treating that as free would report a confidently wrong total.
    """

    model: str
    input: float | None
    output: float | None
    cache_read: float | None
    cache_write: float | None
    cache_write_5m: float | None
    cache_write_1h: float | None
    long_context: bool


class EntryCost(NamedTuple):
    """What one traced request cost, and what it would have cost uncached."""

    cost: float
    uncached_cost: float
    saved: float
    model: str
    long_context: bool


@lru_cache(maxsize=1)
def _price_table() -> dict[str, Any]:
    """Return the vendored price table, or an empty table when unreadable.

    A missing or corrupt price file must degrade to "no cost shown", never
    break viewer generation.
    """
    try:
        payload = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"__meta__": {}, "models": {}}
    if not isinstance(payload, dict):
        return {"__meta__": {}, "models": {}}
    models = payload.get("models")
    meta = payload.get("__meta__")
    return {
        "__meta__": meta if isinstance(meta, dict) else {},
        "models": models if isinstance(models, dict) else {},
    }


def pricing_metadata() -> dict[str, Any]:
    """Return provenance for the price table, for display in the viewer.

    ``upstream_commit`` is what makes a quoted cost reproducible: the fetch date
    alone does not identify a revision of a file that changes several times a
    day, so it travels with the snapshot into the generated viewer.
    """
    meta = _price_table()["__meta__"]
    return {
        "source": meta.get("source", ""),
        "source_url": meta.get("source_url", ""),
        "upstream_commit": meta.get("upstream_commit", ""),
        "as_of": meta.get("fetched_on", ""),
        "model_count": meta.get("model_count", 0),
    }


def model_from_path(path: str) -> str:
    """Extract a model id from a request path.

    Covers Bedrock (``/model/<id>/invoke``) and Vertex/Gemini
    (``/v1beta/models/<id>:streamGenerateContent``) shapes; the character class
    stops at ``:`` so the Vertex method suffix is not captured.
    """
    if not isinstance(path, str):
        return ""
    match = _MODEL_FROM_PATH_RE.search(path)
    return match.group(1) if match else ""


def _candidate_keys(model: str) -> list[str]:
    """Return lookup keys for a model id, most specific first."""
    raw = model.strip()
    if not raw:
        return []
    candidates = [raw]
    stripped = _STRIP_PREFIX_RE.sub("", raw)
    if stripped and stripped != raw:
        candidates.append(stripped)
    # Bedrock appends a version suffix (":0") and prefixes a publisher
    # ("anthropic.claude-..."); Vertex appends "@20240101".
    for base in list(candidates):
        trimmed = base.split(":", 1)[0].split("@", 1)[0]
        if trimmed and trimmed not in candidates:
            candidates.append(trimmed)
        if "." in trimmed:
            tail = trimmed.split(".", 1)[1]
            if tail and tail not in candidates:
                candidates.append(tail)
    return candidates


def _lookup(model: str) -> tuple[str, dict[str, Any]] | None:
    """Resolve a model id to a price entry, or None when unpriced."""
    models = _price_table()["models"]
    for key in _candidate_keys(model):
        entry = models.get(key)
        if isinstance(entry, dict):
            return key, entry
    # Fall back to the longest known id that the model name contains, which
    # catches gateway-prefixed names like "my-pool/claude-opus-5-preview".
    lowered = model.lower()
    best: tuple[str, dict[str, Any]] | None = None
    for key, entry in models.items():
        if not isinstance(entry, dict) or key.lower() not in lowered:
            continue
        if best is None or len(key) > len(best[0]):
            best = (key, entry)
    return best


def _rate(entry: dict[str, Any], field: str, tiered: str | None, long_context: bool) -> float | None:
    """Return the rate for ``field``, or None when the table carries no figure.

    A missing field is reported as None rather than 0.0 so callers can refuse to
    price a bucket instead of silently billing it free.
    """
    if long_context and tiered:
        value = entry.get(tiered)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    value = entry.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def resolve_rates(model: str, *, prompt_tokens: int = 0, cache_ttl_1h: bool = False) -> ModelRates | None:
    """Return rates for ``model``, tiered by ``prompt_tokens``.

    ``prompt_tokens`` is the full prompt size (input plus any cached tokens
    billed separately), because the long-context tier is selected by how large
    the prompt is, not by how much of it was billed at the uncached rate.

    ``cache_ttl_1h`` sets which rate ``cache_write`` reports for callers that
    only handle one TTL; both TTLs are always carried so a request that mixes
    5-minute and 1-hour breakpoints can bill each bucket at its own rate.
    """
    found = _lookup(model or "")
    if found is None:
        return None
    key, entry = found
    long_context = prompt_tokens > LONG_CONTEXT_THRESHOLD and any(
        field in entry
        for field in (
            "input_cost_per_token_above_200k_tokens",
            "output_cost_per_token_above_200k_tokens",
            "cache_read_input_token_cost_above_200k_tokens",
            "cache_creation_input_token_cost_above_200k_tokens",
        )
    )
    write_5m = _rate(
        entry,
        "cache_creation_input_token_cost",
        "cache_creation_input_token_cost_above_200k_tokens",
        long_context,
    )
    # Models without an *_above_1hr field bill both TTLs at the same rate.
    write_1h = _rate(
        entry,
        "cache_creation_input_token_cost_above_1hr",
        "cache_creation_input_token_cost_above_200k_tokens",
        long_context,
    )
    if write_1h is None:
        write_1h = write_5m
    return ModelRates(
        model=key,
        input=_rate(entry, "input_cost_per_token", "input_cost_per_token_above_200k_tokens", long_context),
        output=_rate(entry, "output_cost_per_token", "output_cost_per_token_above_200k_tokens", long_context),
        cache_read=_rate(
            entry,
            "cache_read_input_token_cost",
            "cache_read_input_token_cost_above_200k_tokens",
            long_context,
        ),
        cache_write=write_1h if cache_ttl_1h else write_5m,
        cache_write_5m=write_5m,
        cache_write_1h=write_1h,
        long_context=long_context,
    )


def _int(value: Any) -> int:
    """Coerce a reported token count to a non-negative int.

    A trace can carry ``1e309``, which JSON decodes to ``inf``; ``int(inf)``
    raises, so non-finite values are dropped like any other unusable count.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return max(0, int(value))


def cache_write_buckets(usage: dict[str, Any] | None, *, cache_ttl_1h: bool = False) -> tuple[int, int]:
    """Split cache-creation tokens into (5-minute, 1-hour) buckets.

    Anthropic reports the split under ``usage.cache_creation`` when a request
    mixes breakpoint TTLs. Without it there is only one total, so ``cache_ttl_1h``
    decides which rate it is billed at.
    """
    if not isinstance(usage, dict):
        return (0, 0)
    total = _int(usage.get("cache_creation_input_tokens"))
    detail = usage.get("cache_creation")
    if isinstance(detail, dict):
        write_5m = _int(detail.get("ephemeral_5m_input_tokens"))
        write_1h = _int(detail.get("ephemeral_1h_input_tokens"))
        if write_5m or write_1h:
            # Trust the detailed split, but never bill more than the reported
            # total when the two disagree.
            if total and write_5m + write_1h != total:
                scale = total / (write_5m + write_1h)
                write_1h = round(write_1h * scale)
                write_5m = max(0, total - write_1h)
            return (write_5m, write_1h)
    return (0, total) if cache_ttl_1h else (total, 0)


def entry_cost(model: str, usage: dict[str, Any] | None, *, cache_ttl_1h: bool = False) -> EntryCost | None:
    """Price one traced request, or return None when it cannot be priced.

    ``usage`` must already be normalized by :func:`claude_tap.usage.normalize_usage`,
    which records whether the cache-read count sits inside ``input_tokens`` via
    ``cache_read_in_input``. When it does, those tokens are subtracted from the
    uncached input before billing, so they are charged at the cache-read rate
    only.

    Returns None — rather than a partial figure — when a bucket carries tokens
    the price table has no rate for. ``gpt-4o`` and ``gemini-2.5-pro`` ship with
    no cache-creation cost, and billing those writes at zero would understate the
    turn while still presenting it as fully priced.

    ``saved`` is signed on purpose. A 5-minute cache write costs 1.25x uncached
    input, so a turn that only writes cache is genuinely more expensive than an
    uncached one; clamping that to zero would make every create-then-read session
    overstate its net savings.
    """
    if not isinstance(usage, dict):
        return None

    cache_read = _int(usage.get("cache_read_input_tokens"))
    write_5m, write_1h = cache_write_buckets(usage, cache_ttl_1h=cache_ttl_1h)
    cache_write = write_5m + write_1h
    reported_input = _int(usage.get("input_tokens"))
    output = _int(usage.get("output_tokens"))

    if usage.get("cache_read_in_input") is True:
        uncached_input = max(0, reported_input - cache_read)
        prompt_tokens = reported_input + cache_write
    else:
        uncached_input = reported_input
        prompt_tokens = reported_input + cache_read + cache_write

    if prompt_tokens == 0 and output == 0:
        return None

    rates = resolve_rates(model, prompt_tokens=prompt_tokens, cache_ttl_1h=cache_ttl_1h)
    if rates is None:
        return None

    # Every bucket that carries tokens needs a rate. A rate of None means the
    # table is silent, which is not the same as free.
    billed = (
        (uncached_input, rates.input),
        (cache_read, rates.cache_read),
        (write_5m, rates.cache_write_5m),
        (write_1h, rates.cache_write_1h),
        (output, rates.output),
    )
    if any(tokens and rate is None for tokens, rate in billed):
        return None

    cost = sum(tokens * (rate or 0.0) for tokens, rate in billed)
    # What the same turn would have cost with no cache at all: every prompt
    # token billed as fresh input.
    input_rate = rates.input or 0.0
    uncached_cost = (uncached_input + cache_read + cache_write) * input_rate + output * (rates.output or 0.0)
    return EntryCost(
        cost=cost,
        uncached_cost=uncached_cost,
        saved=uncached_cost - cost,
        model=rates.model,
        long_context=rates.long_context,
    )
