import asyncio

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import app as app_module
from dual_wield_mcp.tools.app import register_app_tools


class _FakeProcess:
    def __init__(self, pid):
        self.pid = pid


def _build_mcp(monkeypatch, tmp_path, popen_result=None, popen_exc=None):
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if popen_exc is not None:
            raise popen_exc
        return popen_result or _FakeProcess(pid=12345)

    monkeypatch.setattr(app_module.subprocess, "Popen", fake_popen)

    config = ServerConfig(screenshot_dir=tmp_path)
    mcp = FastMCP("test")
    register_app_tools(mcp, config)
    return mcp, calls


def test_launch_app_runs_command_with_args(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    result = asyncio.run(
        mcp.call_tool("launch_app", {"command": "brave", "args": ["https://kali.org"]})
    )

    assert len(calls) == 1
    cmd, _kwargs = calls[0]
    assert cmd == ["brave", "https://kali.org"]
    assert "12345" in result[1]["result"]


def test_launch_app_without_args(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("launch_app", {"command": "kwrite"}))

    cmd, _kwargs = calls[0]
    assert cmd == ["kwrite"]


def test_launch_app_is_detached_and_not_waited_on(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("launch_app", {"command": "brave"}))

    _cmd, kwargs = calls[0]
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdout") is app_module.subprocess.DEVNULL
    assert kwargs.get("stderr") is app_module.subprocess.DEVNULL


def test_launch_app_rejects_empty_command(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("launch_app", {"command": ""}))
    assert calls == []


def test_launch_app_binary_not_found_raises_tool_error(monkeypatch, tmp_path):
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, popen_exc=FileNotFoundError("no such file"))
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("launch_app", {"command": "nonexistent-binary"}))
