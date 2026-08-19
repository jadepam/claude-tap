#!/usr/bin/env python3
"""Regenerate claude_tap/model_prices.json from LiteLLM's public price table.

The upstream file is ~1.8 MB and covers every model LiteLLM knows, including
embeddings, rerankers and providers claude-tap cannot proxy. Vendoring it whole
would dwarf the rest of the package data, so this script keeps only chat models
from providers claude-tap can capture, and only the fields the pricing adapter
reads.

Usage:
    python scripts/refresh_model_prices.py            # fetch upstream
    python scripts/refresh_model_prices.py --from FILE # reuse a local copy
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

UPSTREAM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "claude_tap" / "model_prices.json"

# Providers whose traffic claude-tap can actually capture. Anything else only
# inflates the vendored file.
KEPT_PROVIDERS = {
    "anthropic",
    "azure",
    "azure_ai",
    "bedrock",
    "bedrock_converse",
    "deepseek",
    "gemini",
    "groq",
    "mistral",
    "moonshot",
    "openai",
    "openrouter",
    "text-completion-openai",
    "vertex_ai-anthropic_models",
    "vertex_ai-language-models",
    "xai",
}

# Fields the pricing adapter reads. Everything else (search context pricing,
# vision surcharges, rate limits) is dropped.
KEPT_FIELDS = (
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
)


def _fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def prune(upstream: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of upstream entries the pricing adapter can use."""
    pruned: dict[str, Any] = {}
    for name, entry in upstream.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("mode") != "chat":
            continue
        if entry.get("litellm_provider") not in KEPT_PROVIDERS:
            continue
        if entry.get("input_cost_per_token") is None and entry.get("output_cost_per_token") is None:
            continue
        kept = {field: entry[field] for field in KEPT_FIELDS if entry.get(field) is not None}
        if kept:
            pruned[name] = kept
    return pruned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", help="Read upstream JSON from a local file")
    parser.add_argument("--upstream-commit", default="", help="Upstream commit sha for provenance")
    args = parser.parse_args(argv)

    if args.source:
        upstream = json.loads(Path(args.source).read_text(encoding="utf-8"))
    else:
        upstream = _fetch(UPSTREAM_URL)

    models = prune(upstream)
    if not models:
        print("refresh_model_prices: pruning produced no models", file=sys.stderr)
        return 1

    payload = {
        "__meta__": {
            "source": "BerriAI/litellm model_prices_and_context_window.json",
            "source_url": UPSTREAM_URL,
            "upstream_commit": args.upstream_commit,
            "fetched_on": date.today().isoformat(),
            "model_count": len(models),
        },
        "models": dict(sorted(models.items())),
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n",
        encoding="utf-8",
    )
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"wrote {OUTPUT_PATH} ({len(models)} models, {size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
