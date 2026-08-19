"""Provenance classification and session titling, on the Python side.

The viewer decides these twice: `sidebar.js` runs in the browser for small
captures, `viewer.py` precomputes them for lazy metadata above LAZY_THRESHOLD.
The two must agree, or a group's title and badge change as a capture grows past
the threshold. `tests/test_viewer_js_units.py` covers the same cases against the
JS; the assertions here are deliberately the mirror image of those.
"""

from __future__ import annotations

from claude_tap.viewer import (
    _classify_user_input_origin,
    _clean_session_user_text,
    _eligible_user_text_blocks,
    _preferred_user_text_for_message,
    _session_user_text,
)

# Openers a harness wraps a user-role message in. Not prose the user typed, so
# they must neither title a session nor read as human in the detail pane.
INJECTED_OPENERS = [
    "<system-reminder>\nBudget remaining: 40%\n</system-reminder>",
    "<environment_context>\ncwd: /tmp\n</environment_context>",
    "<session_context>\nid: abc\n</session_context>",
    "<local-command-caveat>\nOutput below\n</local-command-caveat>",
    "# AGENTS.md instructions\n\nRun ruff before committing.",
    "# Files mentioned by the user:\n\n- viewer.py",
]


def _user(*blocks: dict | str) -> dict:
    return {"role": "user", "content": list(blocks)}


def _blocks(content: object) -> list[str]:
    return _eligible_user_text_blocks(content)


def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def test_injected_openers_classify_as_harness_and_clean_to_nothing() -> None:
    for opener in INJECTED_OPENERS:
        assert _classify_user_input_origin(opener) == "harness", opener
        assert _clean_session_user_text(opener) == "", opener


def test_wrapper_tags_match_whole_tags_not_prefixes() -> None:
    """`<skillsets>` starts with `<skills` but is not the injected `<skills>` tag."""
    assert _classify_user_input_origin("<skillsets> are what I need here") == "human"


def test_injection_beside_a_tool_result_is_still_seen() -> None:
    """Tool output comes first on the wire, so joined text read as human prose."""
    message = _user(
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
        _text("[SUGGESTION MODE: Suggest what the user might naturally type next.]"),
    )
    text, origin = _preferred_user_text_for_message(message)
    assert origin == "harness"
    # Blank on purpose: the badge is kept, the title is left to an older turn.
    assert text == ""


def test_pasted_payload_followed_by_prose_is_titled_by_the_prose() -> None:
    message = _user(
        _text("import os\nimport sys\n\ndef main():\n    return 0"),
        _text("Does this look right?"),
    )
    assert _preferred_user_text_for_message(message) == ("Does this look right?", "human")


def test_whitespace_only_blocks_do_not_become_the_title() -> None:
    message = _user(_text("  \n  "), _text("Ship it."))
    assert _preferred_user_text_for_message(message) == ("Ship it.", "human")


def test_a_message_with_no_eligible_blocks_yields_no_title() -> None:
    assert _preferred_user_text_for_message({"role": "user", "content": []}) == ("", "human")


def test_session_title_comes_from_the_newest_human_turn() -> None:
    """A cumulative request carries its history; the newest prompt is the query."""
    messages = [
        _user(_text("Human turn A")),
        {"role": "assistant", "content": [_text("...")]},
        _user(_text("Human turn B")),
    ]
    assert _session_user_text(messages) == "Human turn B"


def test_injected_newest_turn_does_not_take_the_session_title() -> None:
    """An injected-only follow-up belongs to the query it follows, not its own group."""
    messages = [
        _user(_text("Split the pull request into two.")),
        {"role": "assistant", "content": [_text("...")]},
        _user(_text("[SUGGESTION MODE: Suggest what the user might naturally type next.]")),
    ]
    assert _session_user_text(messages) == "Split the pull request into two."


def test_eligible_blocks_tolerate_every_content_shape_captures_arrive_in() -> None:
    """Clients disagree about how a user message is shaped, hence this helper."""
    assert _blocks(None) == []
    assert _blocks("plain string") == ["plain string"]
    assert _blocks(42) == []

    # A bare block instead of a list.
    assert _blocks(_text("solo block")) == ["solo block"]
    assert _blocks({"type": "tool_result", "content": "output"}) == []
    assert _blocks({"type": "function_call_output", "output": "output"}) == []
    assert _blocks({"type": "message", "content": [_text("nested")]}) == ["nested"]
    assert _blocks({"type": "text"}) == []

    # Lists mixing strings, blocks, junk, and Responses-style nesting.
    assert _blocks(["loose", _text("keep"), 7, None]) == ["loose", "keep"]
    assert _blocks([{"type": "message", "content": [_text("a"), _text("b")]}]) == ["a", "b"]
    assert _blocks([{"type": "input_text", "output": "from output key"}]) == ["from output key"]

    # Blank blocks would title a group with an empty string.
    assert _blocks([_text("   "), _text("real")]) == ["real"]


def test_session_wrapped_prose_survives_cleaning() -> None:
    """A `<session>` wrapper holds the prompt, unlike the injected wrappers."""
    assert _clean_session_user_text("<session>[Image #1] what does this show?</session>") == "what does this show?"
    assert _clean_session_user_text("<session>[Image #1]</session>") == "[Image #1]"


def test_blank_and_unrecognized_text_reads_as_human() -> None:
    assert _classify_user_input_origin("") == "human"
    assert _classify_user_input_origin("Just a normal question.") == "human"


def test_tool_result_only_turns_never_title_a_session() -> None:
    messages = [
        _user(_text("Run the tests.")),
        {"role": "assistant", "content": [_text("...")]},
        _user({"type": "tool_result", "tool_use_id": "toolu_1", "content": "1102 passed"}),
    ]
    assert _session_user_text(messages) == "Run the tests."
