from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_tap.session_briefing import TOOL_RESULT_MIN_BYTES, summarize_session, summarize_session_from_metadata
from claude_tap.summary import summary_main
from tests.test_viewer_contracts import _session_briefing_records


def test_summarize_session_reports_cost_cache_break_and_large_tool() -> None:
    briefing = summarize_session(list(_session_briefing_records()))

    assert briefing["version"] == 1
    assert briefing["cost"]["usd"] is not None
    assert briefing["cost"]["usd"] > 0
    assert briefing["cost"]["after_turn"] == 2
    assert briefing["cost"]["after_share"] is not None
    assert 0 < briefing["cost"]["after_share"] <= 1
    assert briefing["cache"]["break_turn"] == 2
    assert briefing["cache"]["reason"] == "cache_miss_system"
    assert briefing["tool_results"][0]["name"] == "Read"
    assert briefing["tool_results"][0]["bytes"] == 25000
    assert briefing["tool_results"][0]["turn"] == 2


def test_summarize_session_skips_image_blocks_and_small_results() -> None:
    records = [
        {
            "turn": 1,
            "request_id": "req_small",
            "request": {
                "method": "POST",
                "path": "/v1/messages",
                "headers": {},
                "body": {
                    "model": "claude-opus-5",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "content": [
                                        {"type": "image", "source": {"type": "base64", "data": "x" * 50000}},
                                        {"type": "text", "text": "tiny"},
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
            "response": {
                "status": 200,
                "body": {"usage": {"input_tokens": 10, "output_tokens": 4}},
            },
        }
    ]

    briefing = summarize_session(records)
    assert briefing["tool_results"] == []
    assert all(item["bytes"] >= TOOL_RESULT_MIN_BYTES for item in briefing["tool_results"])


def test_summarize_session_from_metadata_keeps_cost_without_tool_bodies() -> None:
    full = summarize_session(list(_session_briefing_records()))
    from claude_tap.viewer import _extract_metadata_from_record

    metadata = [_extract_metadata_from_record(record) for record in _session_briefing_records()]
    briefing = summarize_session_from_metadata([item for item in metadata if item is not None])

    assert briefing["cost"]["usd"] == full["cost"]["usd"]
    assert briefing["cache"]["break_turn"] == 2
    assert briefing["cache"]["reason"] is None
    assert briefing["tool_results"] == []


def test_summary_cli_prints_the_same_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trace = tmp_path / "briefing.jsonl"
    trace.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in _session_briefing_records()),
        encoding="utf-8",
    )

    assert summary_main([str(trace)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == summarize_session(list(_session_briefing_records()))


def test_summary_cli_rejects_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.jsonl"
    assert summary_main([str(missing)]) == 1
    assert "not found" in capsys.readouterr().err
