import asyncio

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import clipboard as clipboard_module
from dual_wield_mcp.tools.clipboard import register_clipboard_tools


def _build_mcp(monkeypatch, tmp_path, output=""):
    calls = []

    def fake_run(cmd, input_text=None):
        calls.append((cmd, input_text))
        return output

    monkeypatch.setattr(clipboard_module, "_run", fake_run)

    config = ServerConfig(screenshot_dir=tmp_path, wl_copy_path="wl-copy", wl_paste_path="wl-paste")
    mcp = FastMCP("test")
    register_clipboard_tools(mcp, config)
    return mcp, calls


def test_clipboard_set_pipes_text_to_wl_copy(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    result = asyncio.run(mcp.call_tool("clipboard_set", {"text": "hello world"}))

    assert calls == [(["wl-copy"], "hello world")]
    assert "11 chars" in result[1]["result"]


def test_clipboard_set_rejects_empty(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("clipboard_set", {"text": ""}))
    assert calls == []


def test_clipboard_get_reads_wl_paste_no_newline(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, output="clipboard contents")
    result = asyncio.run(mcp.call_tool("clipboard_get", {}))

    assert calls == [(["wl-paste", "--no-newline"], None)]
    assert result[1]["result"] == "clipboard contents"


def test_clipboard_set_binary_not_found_raises(monkeypatch, tmp_path):
    def fake_run(cmd, input_text=None):
        raise ToolError(f"{cmd[0]} not found")

    monkeypatch.setattr(clipboard_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, wl_copy_path="wl-copy")
    mcp = FastMCP("test")
    register_clipboard_tools(mcp, config)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("clipboard_set", {"text": "hi"}))
