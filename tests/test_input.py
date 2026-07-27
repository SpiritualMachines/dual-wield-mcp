import asyncio

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import input as input_module
from dual_wield_mcp.tools.input import register_input_tools


@pytest.fixture(autouse=True)
def _clear_module_caches():
    # display scale and calibrated move ratio are cached across mouse_move calls by
    # design (see input.py) -- reset between tests so one test's cache can't leak
    # into another's assertions
    input_module._display_scale_cache.clear()
    input_module._move_ratio_cache.clear()
    yield
    input_module._display_scale_cache.clear()
    input_module._move_ratio_cache.clear()


def _build_mcp(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)

    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake_run)

    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    mcp = FastMCP("test")
    register_input_tools(mcp, config)
    return mcp, calls, config


class _FakeCursor:
    """Simulates kscreen-doctor (display scale), kdotool getmouselocation (cursor
    position), and ydotool mousemove (relative move) so mouse_move's closed-loop
    correction can be exercised end-to-end without touching real subprocesses.
    Positions are tracked in physical pixels; kdotool reports back in logical
    (scale-divided) pixels, same as the real tools.
    """

    def __init__(self, config, scale, start_x, start_y, ratio_x, ratio_y):
        self.config = config
        self.scale = scale
        self.x = start_x
        self.y = start_y
        self.ratio_x = ratio_x
        self.ratio_y = ratio_y
        self.calls = []

    def run(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == self.config.kscreen_doctor_path:
            return f'{{"outputs":[{{"enabled":true,"scale":{self.scale}}}]}}'
        if cmd[0] == self.config.kdotool_path and cmd[1] == "getmouselocation":
            logical_x = self.x / self.scale
            logical_y = self.y / self.scale
            return f"x:{logical_x:.0f} y:{logical_y:.0f} screen:0 window:12345"
        if cmd[0] == self.config.ydotool_path and cmd[1] == "mousemove":
            move_x, move_y = int(cmd[3]), int(cmd[4])
            self.x += move_x * self.ratio_x
            self.y += move_y * self.ratio_y
            return ""
        raise AssertionError(f"unexpected command: {cmd}")


def test_mouse_move_converges_via_closed_loop_correction(monkeypatch, tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    fake = _FakeCursor(config, scale=1.25, start_x=0, start_y=0, ratio_x=2.33, ratio_y=2.33)
    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake.run)

    mcp = FastMCP("test")
    register_input_tools(mcp, config)

    asyncio.run(mcp.call_tool("mouse_move", {"x": 500, "y": 300}))

    assert abs(fake.x - 500) <= input_module._MOUSE_MOVE_TOLERANCE
    assert abs(fake.y - 300) <= input_module._MOUSE_MOVE_TOLERANCE
    # only relative moves are issued -- ydotool's broken --absolute mode is never used
    move_cmds = [c for c in fake.calls if c[0] == "ydotool" and c[1] == "mousemove"]
    assert move_cmds
    for cmd in move_cmds:
        assert "--absolute" not in cmd


def test_mouse_move_logical_space_converts_via_display_scale(monkeypatch, tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    fake = _FakeCursor(config, scale=1.25, start_x=0, start_y=0, ratio_x=2.33, ratio_y=2.33)
    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake.run)

    mcp = FastMCP("test")
    register_input_tools(mcp, config)

    asyncio.run(mcp.call_tool("mouse_move", {"x": 400, "y": 240, "space": "logical"}))

    # target was given in logical pixels (400, 240); at scale 1.25 the physical
    # target is (500, 300), which is what the cursor should have converged to
    assert abs(fake.x - 500) <= input_module._MOUSE_MOVE_TOLERANCE
    assert abs(fake.y - 300) <= input_module._MOUSE_MOVE_TOLERANCE


def test_mouse_move_physical_space_is_default_and_unscaled(monkeypatch, tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    fake = _FakeCursor(config, scale=1.25, start_x=0, start_y=0, ratio_x=2.33, ratio_y=2.33)
    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake.run)

    mcp = FastMCP("test")
    register_input_tools(mcp, config)

    asyncio.run(mcp.call_tool("mouse_move", {"x": 500, "y": 300}))

    assert abs(fake.x - 500) <= input_module._MOUSE_MOVE_TOLERANCE
    assert abs(fake.y - 300) <= input_module._MOUSE_MOVE_TOLERANCE


def test_mouse_move_rejects_unknown_space(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("mouse_move", {"x": 0, "y": 0, "space": "sideways"}))
    assert calls == []


def test_mouse_move_rejects_negative_coordinates(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("mouse_move", {"x": -1, "y": 0}))
    assert calls == []


def test_mouse_move_queries_display_scale_once_across_calls(monkeypatch, tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    fake = _FakeCursor(config, scale=1.25, start_x=500, start_y=300, ratio_x=2.33, ratio_y=2.33)
    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake.run)

    mcp = FastMCP("test")
    register_input_tools(mcp, config)

    asyncio.run(mcp.call_tool("mouse_move", {"x": 500, "y": 300}))
    asyncio.run(mcp.call_tool("mouse_move", {"x": 500, "y": 300}))

    scale_calls = [c for c in fake.calls if c[0] == config.kscreen_doctor_path]
    assert len(scale_calls) == 1


def test_mouse_move_learns_ratio_across_calls(monkeypatch, tmp_path):
    config = ServerConfig(screenshot_dir=tmp_path, ydotool_path="ydotool")
    # true ratio (5.0) is far from the hardcoded initial guess (2.33), so the first
    # call needs more than one correction iteration; the second should benefit from
    # what the first one learned
    fake = _FakeCursor(config, scale=1.0, start_x=0, start_y=0, ratio_x=5.0, ratio_y=5.0)
    monkeypatch.setattr("dual_wield_mcp.tools.input._run", fake.run)

    mcp = FastMCP("test")
    register_input_tools(mcp, config)

    asyncio.run(mcp.call_tool("mouse_move", {"x": 1000, "y": 1000}))
    first_call_moves = len([c for c in fake.calls if c[0] == "ydotool"])

    fake.calls.clear()
    asyncio.run(mcp.call_tool("mouse_move", {"x": 1500, "y": 1500}))
    second_call_moves = len([c for c in fake.calls if c[0] == "ydotool"])

    assert second_call_moves < first_call_moves


def test_mouse_click_left_default(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("mouse_click", {}))
    assert calls == [["ydotool", "click", "0xc0"]]


def test_mouse_click_right(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("mouse_click", {"button": "right"}))
    assert calls == [["ydotool", "click", "0xc1"]]


def test_mouse_click_unknown_button_raises(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("mouse_click", {"button": "nope"}))
    assert calls == []


def test_mouse_click_double_clicks_twice_in_one_call(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)

    result = asyncio.run(mcp.call_tool("mouse_click", {"double": True}))

    assert calls == [["ydotool", "click", "0xc0"], ["ydotool", "click", "0xc0"]]
    assert "double-clicked" in result[1]["result"]


def test_mouse_click_double_sleeps_between_clicks(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    sleep_calls = []
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    asyncio.run(mcp.call_tool("mouse_click", {"double": True}))

    assert sleep_calls == [input_module._DOUBLE_CLICK_INTERVAL]
    assert len(calls) == 2


def test_mouse_click_default_is_single_click(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    result = asyncio.run(mcp.call_tool("mouse_click", {}))
    assert calls == [["ydotool", "click", "0xc0"]]
    assert "clicked" in result[1]["result"]
    assert "double" not in result[1]["result"]


def test_mouse_click_expected_window_match_proceeds(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "kde")
    monkeypatch.setattr(input_module, "_kde_active_window_class", lambda config: "brave-browser")

    asyncio.run(mcp.call_tool("mouse_click", {"expected_window_class": "brave-browser"}))
    assert calls == [["ydotool", "click", "0xc0"]]


def test_mouse_click_expected_window_mismatch_raises_and_does_not_click(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "kde")
    monkeypatch.setattr(input_module, "_kde_active_window_class", lambda config: "zen-browser")

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("mouse_click", {"expected_window_class": "brave-browser"}))
    assert calls == []


def test_mouse_click_expected_window_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "wlroots")

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("mouse_click", {"expected_window_class": "brave-browser"}))
    assert calls == []


def test_mouse_click_without_expected_window_never_detects_backend(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    detect_calls = []
    monkeypatch.setattr(
        input_module, "_detect_backend", lambda config: detect_calls.append(1) or "kde"
    )

    asyncio.run(mcp.call_tool("mouse_click", {}))
    assert detect_calls == []
    assert calls == [["ydotool", "click", "0xc0"]]


def test_type_text_expected_window_checked_before_and_after(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "kde")
    class_calls = []

    def fake_class(config):
        class_calls.append(1)
        return "brave-browser"

    monkeypatch.setattr(input_module, "_kde_active_window_class", fake_class)

    asyncio.run(
        mcp.call_tool("type_text", {"text": "hello", "expected_window_class": "brave-browser"})
    )
    assert len(class_calls) == 2
    assert calls == [["ydotool", "type", "--", "hello"]]


def test_type_text_expected_window_mismatch_before_blocks_typing(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "kde")
    monkeypatch.setattr(input_module, "_kde_active_window_class", lambda config: "zen-browser")

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool("type_text", {"text": "hello", "expected_window_class": "brave-browser"})
        )
    assert calls == []


def test_type_text_expected_window_drift_after_raises(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(input_module, "_detect_backend", lambda config: "kde")
    responses = iter(["brave-browser", "zen-browser"])
    monkeypatch.setattr(input_module, "_kde_active_window_class", lambda config: next(responses))

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool("type_text", {"text": "hello", "expected_window_class": "brave-browser"})
        )
    # typing already happened before the post-check caught the drift
    assert calls == [["ydotool", "type", "--", "hello"]]


def test_key_press_single_key(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("key_press", {"keys": "enter"}))
    assert calls == [["ydotool", "key", "28:1", "28:0"]]


def test_key_press_combo_presses_down_then_releases_in_reverse(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("key_press", {"keys": "ctrl+shift+t"}))
    # leftctrl=29, leftshift=42, t=20
    assert calls == [["ydotool", "key", "29:1", "42:1", "20:1", "20:0", "42:0", "29:0"]]


def test_key_press_unknown_key_raises(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("key_press", {"keys": "notarealkey"}))
    assert calls == []


def test_type_text(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    asyncio.run(mcp.call_tool("type_text", {"text": "hello"}))
    assert calls == [["ydotool", "type", "--", "hello"]]


def test_type_text_rejects_empty(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("type_text", {"text": ""}))
    assert calls == []
