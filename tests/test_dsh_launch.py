from __future__ import annotations

import asyncio

import pytest

from claude_tap import parse_args
from claude_tap.cli import CLIENT_CONFIGS, run_client
from claude_tap.cli_clients import _detect_dsh_target


class _DummyProc:
    def __init__(self) -> None:
        self.pid = 12345
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def test_dsh_registered_in_client_configs() -> None:
    cfg = CLIENT_CONFIGS["dsh"]

    assert cfg.cmd == "dsh"
    assert cfg.label == "DeepSeek Harness"
    assert cfg.default_target == "https://api.deepseek.com"
    assert cfg.base_url_env == "DEEPSEEK_BASE_URL"
    assert cfg.base_url_suffix == ""
    assert cfg.default_proxy_mode == "reverse"


def test_parse_args_dsh_detects_custom_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example.com/v1")

    args = parse_args(["--tap-client", "dsh"])

    assert args.target == "https://deepseek.example.com/v1"
    assert args.proxy_mode == "reverse"


def test_detect_dsh_target_falls_back_to_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    assert _detect_dsh_target() == "https://api.deepseek.com"


@pytest.mark.asyncio
async def test_run_client_dsh_reverse_sets_base_url_and_preserves_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return _DummyProc()

    monkeypatch.setattr("claude_tap.cli.shutil.which", lambda _: "/tmp/dsh")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    code = await run_client(
        43123,
        ["--profile", "headless", "Reply OK"],
        client="dsh",
        proxy_mode="reverse",
    )

    assert code == 0
    assert captured["cmd"] == ("/tmp/dsh", "--profile", "headless", "Reply OK")
    assert captured["env"]["DEEPSEEK_BASE_URL"] == "http://127.0.0.1:43123"


@pytest.mark.asyncio
async def test_run_client_dsh_forward_enables_node_environment_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return _DummyProc()

    monkeypatch.setattr("claude_tap.cli.shutil.which", lambda _: "/tmp/dsh")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    code = await run_client(43123, [], client="dsh", proxy_mode="forward")

    assert code == 0
    assert captured["env"]["HTTPS_PROXY"] == "http://127.0.0.1:43123"
    assert captured["env"]["NODE_USE_ENV_PROXY"] == "1"
