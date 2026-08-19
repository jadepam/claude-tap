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


def test_check_schema_rejects_qualified_any_annotation(tmp_path: Path) -> None:
    source = tmp_path / "bad_qualified_any.py"
    source.write_text("import typing\nvalue: typing.Any = None\n", encoding="utf-8")
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


def test_check_schema_full_scan_rejects_existing_mapping(tmp_path: Path) -> None:
    source = tmp_path / "legacy.py"
    source.write_text("from collections.abc import Mapping\nvalue: Mapping[str, object] = {}\n", encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    spec = importlib.util.spec_from_file_location("check_schema", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_repository([source]) == [
        f"{source}:2: Mapping annotation; use a Pydantic model or explicit JSON boundary"
    ]


def test_check_schema_full_scan_rejects_typed_dict(tmp_path: Path) -> None:
    source = tmp_path / "legacy_typed_dict.py"
    source.write_text("from typing import TypedDict\nclass Payload(TypedDict):\n    value: str\n", encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    spec = importlib.util.spec_from_file_location("check_schema", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_repository([source]) == [f"{source}:2: use a Pydantic BaseModel instead of TypedDict"]


def test_prompt_models_validate_and_serialize() -> None:
    from claude_tap.models import PromptSnapshotModel, PromptToolModel

    tool = PromptToolModel(schema={"type": "object"}, raw={"name": "search"}, name="search")
    snapshot = PromptSnapshotModel(provider="openai", model="gpt-test", tools=(tool,))
    assert snapshot.tools[0].schema == {"type": "object"}
    assert snapshot.model_dump(by_alias=True)["tools"][0]["schema"] == {"type": "object"}


def test_check_schema_script_is_executable() -> None:
    script = Path(__file__).parents[1] / "scripts" / "check_schema.py"
    assert script.exists()
