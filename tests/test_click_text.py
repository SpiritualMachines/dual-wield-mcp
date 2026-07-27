import asyncio
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import click_text as click_text_module
from dual_wield_mcp.tools.click_text import register_click_text_tools

_MATCH = {
    "text": "ClamTk",
    "x": 700,
    "y": 930,
    "width": 80,
    "height": 40,
    "center_x": 775,
    "center_y": 985,
    "confidence": 92.0,
}


def _build_mcp(monkeypatch, tmp_path, matches=None):
    move_calls = []
    click_calls = []
    capture_calls = []

    def fake_find_text(path, query, case_sensitive, tesseract_path):
        return matches if matches is not None else [_MATCH]

    def fake_capture(config, mode, output_path):
        capture_calls.append((mode, output_path))
        return Path("/tmp/fresh-screenshot.png")

    def fake_move(config, x, y):
        move_calls.append((x, y))

    def fake_run(cmd):
        click_calls.append(cmd)
        return ""

    monkeypatch.setattr(click_text_module, "_find_text_in_image", fake_find_text)
    monkeypatch.setattr(click_text_module, "_capture_screenshot", fake_capture)
    monkeypatch.setattr(click_text_module, "_move_mouse_absolute", fake_move)
    monkeypatch.setattr(click_text_module, "_ydotool_run", fake_run)
    monkeypatch.setattr(click_text_module, "_check_expected_window", lambda config, cls: None)

    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    mcp = FastMCP("test")
    register_click_text_tools(mcp, config)
    return mcp, move_calls, click_calls, capture_calls


def test_click_text_single_confident_match_clicks(monkeypatch, tmp_path):
    mcp, move_calls, click_calls, _capture = _build_mcp(monkeypatch, tmp_path)

    result = asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk"}))

    assert move_calls == [(775.0, 985.0)]
    assert click_calls == [["ydotool", "click", "0xc0"]]
    assert "ClamTk" in result[1]["result"]


def test_click_text_captures_fresh_screenshot_when_no_path(monkeypatch, tmp_path):
    mcp, _move, _click, capture_calls = _build_mcp(monkeypatch, tmp_path)

    asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk"}))

    assert capture_calls == [("full", None)]


def test_click_text_uses_provided_path_without_capturing(monkeypatch, tmp_path):
    mcp, move_calls, _click, capture_calls = _build_mcp(monkeypatch, tmp_path)

    asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk", "path": "/tmp/existing.png"}))

    assert capture_calls == []
    assert move_calls == [(775.0, 985.0)]


def test_click_text_no_match_raises(monkeypatch, tmp_path):
    mcp, move_calls, click_calls, _capture = _build_mcp(monkeypatch, tmp_path, matches=[])

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("click_text", {"query": "Nonexistent"}))
    assert move_calls == []
    assert click_calls == []


def test_click_text_multiple_matches_raises(monkeypatch, tmp_path):
    mcp, move_calls, click_calls, _capture = _build_mcp(
        monkeypatch, tmp_path, matches=[_MATCH, {**_MATCH, "text": "ClamTk2"}]
    )

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk"}))
    assert move_calls == []
    assert click_calls == []


def test_click_text_low_confidence_raises(monkeypatch, tmp_path):
    low_conf = {**_MATCH, "confidence": 30.0}
    mcp, move_calls, click_calls, _capture = _build_mcp(monkeypatch, tmp_path, matches=[low_conf])

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk"}))
    assert move_calls == []
    assert click_calls == []


def test_click_text_unknown_button_raises_before_ocr(monkeypatch, tmp_path):
    ocr_calls = []

    def fake_find_text(path, query, case_sensitive, tesseract_path):
        ocr_calls.append(1)
        return [_MATCH]

    mcp, move_calls, _click, _capture = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(click_text_module, "_find_text_in_image", fake_find_text)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk", "button": "nope"}))
    assert ocr_calls == []
    assert move_calls == []


def test_click_text_min_confidence_out_of_range_raises(monkeypatch, tmp_path):
    mcp, move_calls, _click, _capture = _build_mcp(monkeypatch, tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk", "min_confidence": 150}))
    assert move_calls == []


def test_click_text_expected_window_mismatch_blocks_click(monkeypatch, tmp_path):
    def fake_check(config, expected):
        raise ToolError("mismatch")

    mcp, move_calls, click_calls, _capture = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(click_text_module, "_check_expected_window", fake_check)

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "click_text", {"query": "ClamTk", "expected_window_class": "brave-browser"}
            )
        )
    assert move_calls == []
    assert click_calls == []


def test_click_text_custom_button(monkeypatch, tmp_path):
    mcp, _move, click_calls, _capture = _build_mcp(monkeypatch, tmp_path)

    asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk", "button": "right"}))

    assert click_calls == [["ydotool", "click", "0xc1"]]


def test_click_text_window_scoped_uses_find_text_in_window(monkeypatch, tmp_path):
    calls = []

    def fake_find_text_in_window(path, query, case_sensitive, config, window):
        calls.append((path, query, case_sensitive, window))
        return [_MATCH]

    mcp, move_calls, _click, _capture = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(click_text_module, "_find_text_in_window", fake_find_text_in_window)

    asyncio.run(
        mcp.call_tool(
            "click_text",
            {"query": "ClamTk", "path": "/tmp/existing.png", "window": "{some-window}"},
        )
    )

    assert calls == [("/tmp/existing.png", "ClamTk", False, "{some-window}")]
    assert move_calls == [(775.0, 985.0)]


def test_click_text_without_window_uses_find_text_in_image(monkeypatch, tmp_path):
    window_calls = []

    def fail(*args, **kwargs):
        window_calls.append(args)
        raise AssertionError("must not scope to a window when window is not given")

    mcp, move_calls, _click, _capture = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(click_text_module, "_find_text_in_window", fail)

    asyncio.run(mcp.call_tool("click_text", {"query": "ClamTk"}))

    assert window_calls == []
    assert move_calls == [(775.0, 985.0)]
