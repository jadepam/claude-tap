from __future__ import annotations

import importlib.util
from pathlib import Path


def test_check_schema_rejects_new_dict_annotation(tmp_path: Path) -> None:
    source = tmp_path / "bad.py"
    source.write_text("value: dict[str, object] = {}\n", encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    spec = importlib.util.spec_from_file_location("check_schema", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_paths({source: {1}}) == [f"{source}:1: dict annotation; use a Pydantic model or JsonObject"]


def test_check_schema_rejects_any_annotation(tmp_path: Path) -> None:
    source = tmp_path / "bad_any.py"
    source.write_text("from typing import Any\nvalue: Any = None\n", encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    spec = importlib.util.spec_from_file_location("check_schema", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_paths({source: {2}}) == [f"{source}:2: new Any annotation; use a Pydantic model or JsonValue"]


def test_check_schema_allows_explicit_json_boundary(tmp_path: Path) -> None:
    source = tmp_path / "good.py"
    source.write_text("from claude_tap.models import JsonObject\nvalue: JsonObject = {}\n", encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    spec = importlib.util.spec_from_file_location("check_schema", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_paths({source: {2}}) == []


def test_prompt_models_validate_and_serialize() -> None:
    from claude_tap.models import PromptSnapshotModel, PromptToolModel

    tool = PromptToolModel(schema={"type": "object"}, raw={"name": "search"}, name="search")
    snapshot = PromptSnapshotModel(provider="openai", model="gpt-test", tools=(tool,))
    assert snapshot.tools[0].schema == {"type": "object"}
    assert snapshot.model_dump(by_alias=True)["tools"][0]["schema"] == {"type": "object"}


def test_check_schema_script_is_executable() -> None:
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    assert script.exists()
