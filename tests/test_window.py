import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import window as window_module
from dual_wield_mcp.tools.window import _detect_backend, register_window_tools

_KDOTOOL_METADATA_OUTPUT = (
    "Welcome — KWrite\n"
    "org.kde.kwrite\n"
    "Window {5a489e17-e299-45ff-902a-8d0a3f2c0956}\n"
    "  Position: 1376,0\n"
    "  Geometry: 1376x1104\n"
    "162595\n"
)


def _build_mcp(monkeypatch, tmp_path, backend, run_map=None):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if run_map is not None:
            for prefix, output in run_map.items():
                if tuple(cmd[: len(prefix)]) == prefix:
                    return output
        return ""

    async def fake_run_async(cmd):
        return fake_run(cmd)

    monkeypatch.setattr(window_module, "_run", fake_run)
    monkeypatch.setattr(window_module, "_run_async", fake_run_async)

    config = ServerConfig(
        screenshot_dir=tmp_path,
        kdotool_path="kdotool",
        wlrctl_path="wlrctl",
        window_backend=backend,
    )
    mcp = FastMCP("test")
    register_window_tools(mcp, config)
    return mcp, calls


def test_detect_backend_explicit_kde(tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="kde")
    assert _detect_backend(config) == "kde"


def test_detect_backend_explicit_wlroots(tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="wlroots")
    assert _detect_backend(config) == "wlroots"


def test_detect_backend_auto_prefers_kde(monkeypatch, tmp_path):
    # deliberately does not set XDG_CURRENT_DESKTOP: MCP clients strip it from the
    # server subprocess environment by default, so detection must not depend on it
    monkeypatch.setattr(window_module.shutil, "which", lambda path: "/usr/bin/" + path)
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="auto")
    assert _detect_backend(config) == "kde"


def test_detect_backend_auto_falls_back_to_wlroots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        window_module.shutil, "which", lambda path: "/usr/bin/wlrctl" if path == "wlrctl" else None
    )
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="auto")
    assert _detect_backend(config) == "wlroots"


def test_detect_backend_auto_raises_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(window_module.shutil, "which", lambda path: None)
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="auto")
    with pytest.raises(ToolError):
        _detect_backend(config)


def test_get_windows_parses_kdotool_output(monkeypatch, tmp_path):
    run_map = {
        ("kdotool", "search", "."): "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n",
        ("kdotool", "getwindowname"): _KDOTOOL_METADATA_OUTPUT,
    }
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)

    result = asyncio.run(mcp.call_tool("get_windows", {}))
    windows = result[1]["result"]

    assert len(windows) == 1
    window = windows[0]
    assert window["id"] == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"
    assert window["title"] == "Welcome — KWrite"
    assert window["class_name"] == "org.kde.kwrite"
    assert window["pid"] == 162595
    assert window["x"] == 1376.0
    assert window["y"] == 0.0
    assert window["width"] == 1376.0
    assert window["height"] == 1104.0


def test_get_windows_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("get_windows", {}))
    assert calls == []


def test_get_windows_fetches_per_window_metadata_concurrently(monkeypatch, tmp_path):
    concurrent = 0
    max_concurrent = 0

    async def fake_run_async(cmd):
        nonlocal concurrent, max_concurrent
        if cmd[1] == "search":
            return "{window-1}\n{window-2}\n{window-3}\n"
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0)  # yield so overlapping in-flight calls can interleave
        concurrent -= 1
        return _KDOTOOL_METADATA_OUTPUT

    monkeypatch.setattr(window_module, "_run_async", fake_run_async)

    config = ServerConfig(screenshot_dir=tmp_path, window_backend="kde")
    mcp = FastMCP("test")
    register_window_tools(mcp, config)

    result = asyncio.run(mcp.call_tool("get_windows", {}))

    assert len(result[1]["result"]) == 3
    assert max_concurrent > 1


def test_get_active_window_parses_kdotool_output(monkeypatch, tmp_path):
    run_map = {
        ("kdotool", "getactivewindow"): "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n",
        ("kdotool", "getwindowname"): _KDOTOOL_METADATA_OUTPUT,
    }
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)

    result = asyncio.run(mcp.call_tool("get_active_window", {}))
    window = json.loads(result[0].text)

    assert window["id"] == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"
    assert window["title"] == "Welcome — KWrite"
    assert window["class_name"] == "org.kde.kwrite"
    assert window["pid"] == 162595


def test_get_active_window_no_active_window_raises(monkeypatch, tmp_path):
    run_map = {("kdotool", "getactivewindow"): "\n"}
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("get_active_window", {}))


def test_get_active_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("get_active_window", {}))
    assert calls == []


def test_kde_active_window_class_parses_kdotool_output(monkeypatch, tmp_path):
    run_map = {
        ("kdotool", "getactivewindow"): "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n",
        ("kdotool", "getwindowclassname", "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"): (
            "org.kde.kwrite\n"
        ),
    }

    def fake_run(cmd):
        for prefix, output in run_map.items():
            if tuple(cmd[: len(prefix)]) == prefix:
                return output
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(window_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")
    assert window_module._kde_active_window_class(config) == "org.kde.kwrite"


def test_kde_active_window_class_no_active_window_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(window_module, "_run", lambda cmd: "\n")
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")
    assert window_module._kde_active_window_class(config) is None


def test_kde_get_window_metadata_sync_parses_kdotool_output(monkeypatch, tmp_path):
    def fake_run(cmd):
        if cmd[:2] == ["kdotool", "getwindowname"]:
            return _KDOTOOL_METADATA_OUTPUT
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(window_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")

    info = window_module._kde_get_window_metadata_sync(
        config, "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"
    )

    assert info is not None
    assert info.title == "Welcome — KWrite"
    assert info.class_name == "org.kde.kwrite"
    assert (info.x, info.y, info.width, info.height) == (1376.0, 0.0, 1376.0, 1104.0)
    assert info.pid == 162595


def test_kde_get_window_metadata_sync_returns_none_on_bad_output(monkeypatch, tmp_path):
    monkeypatch.setattr(window_module, "_run", lambda cmd: "too short\n")
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")

    assert window_module._kde_get_window_metadata_sync(config, "{some-id}") is None


def test_kde_resolve_window_geometry_by_id_skips_search(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:2] == ["kdotool", "getwindowname"]:
            return _KDOTOOL_METADATA_OUTPUT
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(window_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")

    info = window_module._kde_resolve_window_geometry(
        config, "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"
    )

    assert info.width == 1376.0
    assert not any(cmd[1] == "search" for cmd in calls)


def test_kde_resolve_window_geometry_by_title_resolves_first(monkeypatch, tmp_path):
    def fake_run(cmd):
        if cmd[:2] == ["kdotool", "search"]:
            return "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n"
        if cmd[:2] == ["kdotool", "getwindowname"]:
            return _KDOTOOL_METADATA_OUTPUT
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(window_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")

    info = window_module._kde_resolve_window_geometry(config, "KWrite")

    assert info.id == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"


def test_kde_resolve_window_geometry_raises_on_bad_metadata(monkeypatch, tmp_path):
    def fake_run(cmd):
        if cmd[:2] == ["kdotool", "getwindowname"]:
            return "too short\n"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(window_module, "_run", fake_run)
    config = ServerConfig(screenshot_dir=tmp_path, kdotool_path="kdotool")

    with pytest.raises(ToolError):
        window_module._kde_resolve_window_geometry(config, "{some-id}")


def test_wait_for_window_matches_immediately_by_class(monkeypatch, tmp_path):
    run_map = {
        ("kdotool", "search", "."): "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n",
        ("kdotool", "getwindowname"): _KDOTOOL_METADATA_OUTPUT,
    }
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)

    result = asyncio.run(
        mcp.call_tool("wait_for_window", {"window_class": "org.kde.kwrite", "timeout": 5.0})
    )
    window = json.loads(result[0].text)
    assert window["id"] == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"
    assert window["title"] == "Welcome — KWrite"


def test_wait_for_window_matches_by_title_substring_case_insensitive(monkeypatch, tmp_path):
    run_map = {
        ("kdotool", "search", "."): "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n",
        ("kdotool", "getwindowname"): _KDOTOOL_METADATA_OUTPUT,
    }
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)

    result = asyncio.run(mcp.call_tool("wait_for_window", {"title": "kwrite", "timeout": 5.0}))
    window = json.loads(result[0].text)
    assert window["id"] == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"


def test_wait_for_window_polls_until_match_appears(monkeypatch, tmp_path):
    monkeypatch.setattr(window_module, "_WAIT_FOR_WINDOW_POLL_INTERVAL", 0.01)
    search_results = iter(["\n", "\n", "{5a489e17-e299-45ff-902a-8d0a3f2c0956}\n"])

    async def fake_run_async(cmd):
        if cmd[1] == "search":
            return next(search_results)
        return _KDOTOOL_METADATA_OUTPUT

    monkeypatch.setattr(window_module, "_run_async", fake_run_async)
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="kde")
    mcp = FastMCP("test")
    register_window_tools(mcp, config)

    result = asyncio.run(
        mcp.call_tool("wait_for_window", {"window_class": "org.kde.kwrite", "timeout": 5.0})
    )
    window = json.loads(result[0].text)
    assert window["id"] == "{5a489e17-e299-45ff-902a-8d0a3f2c0956}"


def test_wait_for_window_times_out_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(window_module, "_WAIT_FOR_WINDOW_POLL_INTERVAL", 0.01)

    async def fake_run_async(cmd):
        return ""

    monkeypatch.setattr(window_module, "_run_async", fake_run_async)
    config = ServerConfig(screenshot_dir=tmp_path, window_backend="kde")
    mcp = FastMCP("test")
    register_window_tools(mcp, config)

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool("wait_for_window", {"window_class": "brave-browser", "timeout": 0.05})
        )


def test_wait_for_window_requires_title_or_class(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("wait_for_window", {}))
    assert calls == []


def test_wait_for_window_rejects_non_positive_timeout(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool("wait_for_window", {"window_class": "brave-browser", "timeout": 0})
        )
    assert calls == []


def test_wait_for_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("wait_for_window", {"window_class": "brave-browser"}))
    assert calls == []


def test_focus_window_by_id_skips_search(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    asyncio.run(mcp.call_tool("focus_window", {"window": "{some-uuid}"}))
    assert calls == [["kdotool", "windowactivate", "{some-uuid}"]]


def test_focus_window_by_title_searches_then_activates(monkeypatch, tmp_path):
    run_map = {("kdotool", "search", "--limit", "1"): "{found-uuid}\n"}
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    asyncio.run(mcp.call_tool("focus_window", {"window": "KWrite"}))
    assert calls == [
        ["kdotool", "search", "--limit", "1", "KWrite"],
        ["kdotool", "windowactivate", "{found-uuid}"],
    ]


def test_focus_window_by_title_not_found_raises(monkeypatch, tmp_path):
    run_map = {("kdotool", "search", "--limit", "1"): ""}
    mcp, _calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("focus_window", {"window": "Nonexistent"}))


def test_focus_window_empty_raises(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("focus_window", {"window": ""}))
    assert calls == []


def test_focus_window_wlroots_backend(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    asyncio.run(mcp.call_tool("focus_window", {"window": "Firefox"}))
    assert calls == [["wlrctl", "toplevel", "focus", "title:Firefox"]]


def test_close_window_by_id_skips_search(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    asyncio.run(mcp.call_tool("close_window", {"window": "{some-uuid}"}))
    assert calls == [["kdotool", "windowclose", "{some-uuid}"]]


def test_close_window_by_title_searches_then_closes(monkeypatch, tmp_path):
    run_map = {("kdotool", "search", "--limit", "1"): "{found-uuid}\n"}
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    asyncio.run(mcp.call_tool("close_window", {"window": "KWrite"}))
    assert calls == [
        ["kdotool", "search", "--limit", "1", "KWrite"],
        ["kdotool", "windowclose", "{found-uuid}"],
    ]


def test_close_window_empty_raises(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("close_window", {"window": ""}))
    assert calls == []


def test_close_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("close_window", {"window": "Firefox"}))
    assert calls == []


def test_move_window_by_id_skips_search(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    asyncio.run(mcp.call_tool("move_window", {"window": "{some-uuid}", "x": 100, "y": 200}))
    assert calls == [["kdotool", "windowmove", "{some-uuid}", "100", "200"]]


def test_move_window_by_title_searches_then_moves(monkeypatch, tmp_path):
    run_map = {("kdotool", "search", "--limit", "1"): "{found-uuid}\n"}
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    asyncio.run(mcp.call_tool("move_window", {"window": "KWrite", "x": 0, "y": 0}))
    assert calls == [
        ["kdotool", "search", "--limit", "1", "KWrite"],
        ["kdotool", "windowmove", "{found-uuid}", "0", "0"],
    ]


def test_move_window_allows_negative_coordinates(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    asyncio.run(mcp.call_tool("move_window", {"window": "{uuid}", "x": -100, "y": 0}))
    assert calls == [["kdotool", "windowmove", "{uuid}", "-100", "0"]]


def test_move_window_empty_raises(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("move_window", {"window": "", "x": 0, "y": 0}))
    assert calls == []


def test_move_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("move_window", {"window": "Firefox", "x": 0, "y": 0}))
    assert calls == []


def test_resize_window_by_id_skips_search(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    asyncio.run(
        mcp.call_tool("resize_window", {"window": "{some-uuid}", "width": 800, "height": 600})
    )
    assert calls == [["kdotool", "windowsize", "{some-uuid}", "800", "600"]]


def test_resize_window_by_title_searches_then_resizes(monkeypatch, tmp_path):
    run_map = {("kdotool", "search", "--limit", "1"): "{found-uuid}\n"}
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde", run_map)
    asyncio.run(mcp.call_tool("resize_window", {"window": "KWrite", "width": 800, "height": 600}))
    assert calls == [
        ["kdotool", "search", "--limit", "1", "KWrite"],
        ["kdotool", "windowsize", "{found-uuid}", "800", "600"],
    ]


def test_resize_window_rejects_non_positive_dimensions(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("resize_window", {"window": "{uuid}", "width": 0, "height": 600}))
    assert calls == []


def test_resize_window_empty_raises(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "kde")
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("resize_window", {"window": "", "width": 800, "height": 600}))
    assert calls == []


def test_resize_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls = _build_mcp(monkeypatch, tmp_path, "wlroots")
    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool("resize_window", {"window": "Firefox", "width": 800, "height": 600})
        )
    assert calls == []


def test_backend_detected_once_at_registration_not_per_call(monkeypatch, tmp_path):
    detect_calls = []
    real_detect_backend = window_module._detect_backend

    def counting_detect_backend(config):
        detect_calls.append(config)
        return real_detect_backend(config)

    monkeypatch.setattr(window_module, "_detect_backend", counting_detect_backend)
    monkeypatch.setattr(window_module, "_run", lambda cmd: "")

    config = ServerConfig(screenshot_dir=tmp_path, window_backend="kde")
    mcp = FastMCP("test")
    register_window_tools(mcp, config)
    assert len(detect_calls) == 1

    asyncio.run(mcp.call_tool("focus_window", {"window": "{uuid-a}"}))
    asyncio.run(mcp.call_tool("focus_window", {"window": "{uuid-b}"}))
    assert len(detect_calls) == 1
