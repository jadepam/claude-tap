"""Regression tests for the CI workflow's dependency and browser-cache contract.

The Playwright browser cache used to miss on every run, making one step take
20 minutes at the median and over two hours at the worst. Two independent
defects caused it, and both are cheap to assert on statically:

1. The cache key hashed `uv.lock` while pip installed from `pyproject.toml`,
   where playwright was declared in a PEP 735 `[dependency-groups]` table that
   pip cannot read. pip therefore resolved an unpinned latest playwright whose
   browser revision was never the one in the restored cache.
2. `restore-keys` let a stale prefix satisfy the restore, while the unchanging
   primary key still counted as a hit and suppressed the post-step save, so the
   cache could never converge on the revision actually in use.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def test_playwright_is_pinned_where_pip_can_read_it() -> None:
    """pip only reads [project.optional-dependencies], never PEP 735 groups."""
    dev_extra = _pyproject()["project"]["optional-dependencies"]["dev"]
    pins = [spec for spec in dev_extra if spec.replace("-", "_").startswith("playwright")]

    assert pins, "playwright must live in the dev extra so `pip install -e '.[dev]'` resolves it"
    assert pins == ["playwright==1.58.0"], (
        "playwright must stay exactly pinned: the browser cache key hashes pyproject.toml, "
        "and a floating spec would install a version whose browser revision is not cached"
    )


def test_dependency_group_does_not_redeclare_dev_tooling() -> None:
    """The uv group aliases the extra so both installers agree on one list."""
    assert _pyproject()["dependency-groups"]["dev"] == ["claude-tap[dev]"]


def test_browser_cache_key_hashes_the_file_that_pins_playwright() -> None:
    workflow = _workflow_text()

    assert "${{ runner.os }}-playwright-${{ hashFiles('pyproject.toml') }}" in workflow
    assert "${{ runner.os }}-playwright-${{ hashFiles('uv.lock') }}" not in workflow


def test_browser_cache_has_no_prefix_fallback() -> None:
    """A prefix hit restores a directory missing the current browser revision."""
    workflow = _workflow_text()

    # Match the YAML key, not prose: the workflow comments explain the pitfall.
    assert "restore-keys:" not in workflow


def test_browser_download_is_skipped_on_a_cache_hit() -> None:
    workflow = _workflow_text()

    assert "steps.playwright-cache.outputs.cache-hit != 'true'" in workflow
    assert "python -m playwright install chromium" in workflow
    # System libraries live outside the cached path, so they install every run.
    assert "python -m playwright install-deps chromium" in workflow
    assert "playwright install --with-deps chromium" not in workflow


def test_coverage_job_does_not_reinstall_playwright_outside_the_pin() -> None:
    """`pip install ... playwright` next to the extra would defeat the pin."""
    workflow = _workflow_text()

    assert 'pip install -e ".[dev]" playwright' not in workflow
