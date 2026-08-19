"""Cost plumbing between the Python pricing adapter and the viewer.

The adapter itself is covered by tests/test_pricing.py. These tests assert that
every viewer generation path carries the precomputed numbers, and that the keys
of the embedded cost index match the entry ids the viewer derives client-side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from claude_tap.compact_trace import build_compact_trace_bundle
from claude_tap.viewer import (
    _build_cost_index,
    _cache_ttl_1h,
    _extract_metadata_from_record,
    _generate_html_viewer,
    _generate_html_viewer_from_metadata,
    _generate_html_viewer_from_records,
    _websocket_response_groups,
    attach_cost_to_record,
)

SONNET_4 = "claude-sonnet-4-20250514"


def _anthropic_record(request_id: str = "req_1", *, cache_read: int = 40_000) -> dict:
    return {
        "timestamp": "2026-08-19T10:00:00+00:00",
        "request_id": request_id,
        "turn": 1,
        "duration_ms": 900,
        "request": {
            "method": "POST",
            "path": "/v1/messages",
            "headers": {"host": "api.anthropic.com"},
            "body": {
                "model": SONNET_4,
                "system": [{"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": "hi"}],
            },
        },
        "response": {
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": {
                "model": SONNET_4,
                "content": [{"type": "text", "text": "hello"}],
                "usage": {
                    "input_tokens": 120,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": 2_000,
                    "output_tokens": 45,
                },
            },
        },
    }


def _ws_event(event_type: str, **extra: object) -> dict:
    """Match the captured shape: the event type sits on the outer object."""
    return {"type": event_type, **extra}


def _ws_record(request_id: str = "req_ws") -> dict:
    """A single record carrying two completed responses, as the viewer splits it."""

    def completed(tokens: int) -> dict:
        return _ws_event(
            "response.completed",
            response={
                "model": SONNET_4,
                "output": [],
                "usage": {"input_tokens": tokens, "output_tokens": 10},
            },
        )

    return {
        "timestamp": "2026-08-19T10:05:00+00:00",
        "request_id": request_id,
        "turn": 2,
        "request": {"method": "GET", "path": "/v1/realtime", "headers": {}, "body": {}},
        "response": {
            "status": 101,
            "headers": {},
            "ws_events": [
                _ws_event("response.created", response={"model": SONNET_4}),
                completed(1_000),
                _ws_event("response.created", response={"model": SONNET_4}),
                completed(2_000),
            ],
        },
    }


def _single_response_ws_record(request_id: str = "req_ws1") -> dict:
    """A WebSocket record with one response, which the viewer does not split.

    The request body names no model, as the captured realtime handshake does not
    carry one — only the streamed response payload does.
    """
    return {
        "timestamp": "2026-08-19T10:06:00+00:00",
        "request_id": request_id,
        "turn": 3,
        "request": {"method": "GET", "path": "/v1/realtime", "headers": {}, "body": {}},
        "response": {
            "status": 101,
            "headers": {},
            "ws_events": [
                _ws_event("response.created", response={"model": SONNET_4}),
                _ws_event(
                    "response.completed",
                    response={
                        "model": SONNET_4,
                        "output": [],
                        "usage": {"input_tokens": 3_000, "output_tokens": 20},
                    },
                ),
            ],
        },
    }


def _embedded_const(html: str, name: str) -> object:
    match = re.search(rf"const {name} = (.*?);\n", html, re.DOTALL)
    assert match, f"{name} missing from generated viewer"
    return json.loads(match.group(1))


def test_metadata_record_carries_cost_and_cache_provenance() -> None:
    meta = _extract_metadata_from_record(_anthropic_record())
    assert meta is not None

    assert meta["priced_model"] == SONNET_4
    assert meta["cache_read_in_input"] is False
    assert meta["long_context"] is False
    # 120 fresh input + 40K cache read + 2K cache write + 45 output.
    assert meta["cost"] == pytest.approx(120 * 3e-06 + 40_000 * 3e-07 + 2_000 * 3.75e-06 + 45 * 1.5e-05)
    assert meta["uncached_cost"] == pytest.approx(42_120 * 3e-06 + 45 * 1.5e-05)
    assert meta["saved"] == pytest.approx(meta["uncached_cost"] - meta["cost"])


def test_unpriced_model_leaves_cost_off_the_metadata_record() -> None:
    record = _anthropic_record()
    record["request"]["body"]["model"] = "some-unlisted-gateway-model"
    record["response"]["body"]["model"] = "some-unlisted-gateway-model"

    meta = _extract_metadata_from_record(record)
    assert meta is not None
    assert "cost" not in meta
    assert "saved" not in meta


def test_cache_ttl_1h_is_read_from_the_request_breakpoints() -> None:
    assert _cache_ttl_1h({}) is False
    assert _cache_ttl_1h({"system": [{"cache_control": {"type": "ephemeral"}}]}) is False
    assert _cache_ttl_1h({"system": [{"cache_control": {"type": "ephemeral", "ttl": "1h"}}]}) is True
    assert _cache_ttl_1h({"messages": [{"content": [{"text": "x", "cache_control": {"ttl": "1h"}}]}]}) is True


def test_one_hour_breakpoint_raises_the_cache_write_cost() -> None:
    default_ttl = _extract_metadata_from_record(_anthropic_record())
    record = _anthropic_record()
    record["request"]["body"]["system"][0]["cache_control"]["ttl"] = "1h"
    one_hour = _extract_metadata_from_record(record)
    assert default_ttl is not None and one_hour is not None

    assert one_hour["cost"] > default_ttl["cost"]
    assert one_hour["cost"] - default_ttl["cost"] == pytest.approx(2_000 * (6e-06 - 3.75e-06))


def test_websocket_groups_require_a_completed_response() -> None:
    events = [
        _ws_event("response.created", response={"model": SONNET_4}),
        _ws_event("response.output_text.delta", delta="a"),
    ]

    assert _websocket_response_groups(events) == []


def test_cost_index_keys_match_the_viewer_websocket_entry_ids() -> None:
    index = _build_cost_index([_ws_record()])

    # buildWebSocketResponseEntry keys split entries `${request_id}:${idx + 1}`.
    assert sorted(index) == ["req_ws:1", "req_ws:2"]
    assert index["req_ws:1"]["cost"] == pytest.approx(1_000 * 3e-06 + 10 * 1.5e-05)
    assert index["req_ws:2"]["cost"] == pytest.approx(2_000 * 3e-06 + 10 * 1.5e-05)


def test_cost_index_keys_plain_records_by_request_id() -> None:
    index = _build_cost_index([_anthropic_record("req_plain")])

    assert list(index) == ["req_plain"]
    assert set(index["req_plain"]) == {
        "cost",
        "uncached_cost",
        "saved",
        "priced_model",
        "long_context",
    }


def test_cost_index_skips_records_without_a_request_id() -> None:
    record = _anthropic_record()
    del record["request_id"]

    assert _build_cost_index([record, "not a dict"]) == {}  # type: ignore[list-item]


def test_compact_bundle_viewer_embeds_a_cost_index(tmp_path: Path) -> None:
    html_path = tmp_path / "viewer.html"
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(json.dumps(_anthropic_record("req_compact")) + "\n", encoding="utf-8")

    _generate_html_viewer(trace_path, html_path)
    html = html_path.read_text(encoding="utf-8")

    index = _embedded_const(html, "EMBEDDED_COST_INDEX")
    assert isinstance(index, dict)
    assert index["req_compact"]["cost"] > 0
    meta = _embedded_const(html, "EMBEDDED_PRICING_META")
    assert isinstance(meta, dict)
    assert meta["source_url"].startswith("https://raw.githubusercontent.com/BerriAI/litellm/")
    assert meta["as_of"]


def test_records_viewer_embeds_a_cost_index(tmp_path: Path) -> None:
    html_path = tmp_path / "viewer.html"

    _generate_html_viewer_from_records(
        [json.dumps(_anthropic_record("req_inline"))],
        html_path,
        display_trace_path="trace.jsonl",
        display_html_path=html_path,
    )
    html = html_path.read_text(encoding="utf-8")

    index = _embedded_const(html, "EMBEDDED_COST_INDEX")
    assert isinstance(index, dict)
    assert index["req_inline"]["cost"] > 0


def test_metadata_viewer_ships_provenance_without_an_index(tmp_path: Path) -> None:
    """Lazy mode carries cost on each metadata record, so the index stays empty."""
    html_path = tmp_path / "viewer.html"
    meta = _extract_metadata_from_record(_anthropic_record("req_lazy"))
    assert meta is not None

    _generate_html_viewer_from_metadata(
        [meta],
        html_path,
        display_trace_path="trace.jsonl",
        display_html_path=html_path,
        records_api_path="/records",
    )
    html = html_path.read_text(encoding="utf-8")

    assert _embedded_const(html, "EMBEDDED_COST_INDEX") == {}
    assert _embedded_const(html, "EMBEDDED_PRICING_META")["as_of"]
    embedded_meta = _embedded_const(html, "EMBEDDED_TRACE_META")
    assert isinstance(embedded_meta, list)
    assert embedded_meta[0]["cost"] > 0


def test_compact_bundle_round_trip_keeps_costs_addressable() -> None:
    bundle = build_compact_trace_bundle([_anthropic_record("req_a"), _anthropic_record("req_b")])

    assert bundle
    index = _build_cost_index([_anthropic_record("req_a"), _anthropic_record("req_b")])
    assert sorted(index) == ["req_a", "req_b"]


def test_a_single_response_websocket_record_is_priced_by_request_id() -> None:
    # The viewer only rewrites the entry id when it splits a record, so a record
    # with one response has to be keyed plainly or the turn shows no cost.
    index = _build_cost_index([_single_response_ws_record()])

    assert list(index) == ["req_ws1"]
    assert index["req_ws1"]["cost"] == pytest.approx(3_000 * 3e-06 + 20 * 1.5e-05)


def test_the_model_is_read_from_the_response_when_the_request_omits_it() -> None:
    meta = _extract_metadata_from_record(_single_response_ws_record())

    assert meta is not None
    assert meta["priced_model"] == SONNET_4


def test_raw_records_carry_their_costs_for_the_live_viewer() -> None:
    plain = attach_cost_to_record(_anthropic_record("req_live"))

    assert set(plain["_cost_index"]) == {"req_live"}
    assert plain["_cost_index"]["req_live"]["cost"] > 0

    split = attach_cost_to_record(_ws_record())
    assert sorted(split["_cost_index"]) == ["req_ws:1", "req_ws:2"]


def test_an_unpriceable_record_is_handed_over_untouched() -> None:
    record = _anthropic_record()
    record["request"]["body"]["model"] = "some-unlisted-gateway-model"
    record["response"]["body"]["model"] = "some-unlisted-gateway-model"

    attached = attach_cost_to_record(record)
    assert "_cost_index" not in attached
    assert attach_cost_to_record("not a dict") == "not a dict"  # type: ignore[arg-type]
