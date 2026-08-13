#!/usr/bin/env python3
"""Reject new schema-less Python annotations while preserving dynamic JSON edges.

This is intentionally incremental: the repository contains existing provider
protocol code whose payloads are open-ended. New code must use a Pydantic
model, a concrete collection type, or the explicit JsonObject boundary.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

_SCHEMALESS_NAMES = {"Any", "Dict", "TypedDict"}
_BARE_NAMES = {"dict", "Dict", "Any"}
_ALLOWED_FILES = {Path("claude_tap/models.py"), Path("scripts/check_schema.py")}


def _changed_lines(base: str) -> dict[Path, set[int]]:
    result = subprocess.run(
        ["git", "diff", "--unified=0", base, "--", "*.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    changed: dict[Path, set[int]] = {}
    current: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = Path(line[6:])
            changed.setdefault(current, set())
            continue
        if not line.startswith("@@") or current is None:
            continue
        hunk = line.split("+")[1].split(" ", 1)[0]
        start, _, count = hunk.partition(",")
        first = int(start)
        length = int(count or "1")
        changed[current].update(range(first, first + length))
    return changed


def _annotation_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


def _find_violations(path: Path, lines: set[int]) -> list[str]:
    if path in _ALLOWED_FILES or not path.exists():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: unable to parse Python source: {exc.msg}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(base, ast.Name) and base.id == "TypedDict" for base in node.bases
        ):
            if node.lineno in lines:
                violations.append(f"{path}:{node.lineno}: use a Pydantic BaseModel instead of TypedDict")
        annotation = None
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            annotation = node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = node.returns
        if annotation is None or annotation.lineno not in lines:
            continue
        names = _annotation_names(annotation)
        if "Any" in names:
            violations.append(f"{path}:{annotation.lineno}: new Any annotation; use a Pydantic model or JsonValue")
            continue
        if isinstance(annotation, ast.Name) and annotation.id in _BARE_NAMES:
            violations.append(f"{path}:{annotation.lineno}: bare {annotation.id} annotation; use a Pydantic model")
        elif (
            isinstance(annotation, ast.Subscript)
            and isinstance(annotation.value, ast.Name)
            and annotation.value.id
            in {
                "dict",
                "Dict",
            }
        ):
            violations.append(f"{path}:{annotation.lineno}: dict annotation; use a Pydantic model or JsonObject")
    return violations


def check_paths(paths: dict[Path, set[int]]) -> list[str]:
    """Return violations for an already computed changed-line map."""
    return [violation for path, lines in paths.items() for violation in _find_violations(path, lines)]


def _ruff_any_violations(paths: dict[Path, set[int]]) -> list[str]:
    files = [str(path) for path in paths if path.exists() and path.suffix == ".py"]
    if not files:
        return []
    ruff = shutil.which("ruff")
    command = [ruff] if ruff else ["uv", "run", "ruff"]
    result = subprocess.run(
        [*command, "check", "--select", "ANN401", "--output-format", "json", *files],
        check=False,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return []
    findings = json.loads(result.stdout)
    violations: list[str] = []
    for finding in findings:
        path = Path(finding["filename"])
        line = finding["location"]["row"]
        if line in paths.get(path, set()):
            violations.append(f"{path}:{line}: {finding['message']} (Ruff ANN401)")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main", help="Git base used to identify changed lines")
    args = parser.parse_args()
    changed = _changed_lines(args.base)
    violations = check_paths(changed) + _ruff_any_violations(changed)
    if violations:
        print("Incremental schema check failed:")
        print("\n".join(violations))
        return 1
    print("Incremental schema check passed (new annotations are schema-defined or explicit JSON boundaries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
