import asyncio

import pytesseract
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from PIL import Image as PILImage

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools import ocr as ocr_module
from dual_wield_mcp.tools.ocr import _group_words_into_lines, register_ocr_tools
from dual_wield_mcp.tools.window import WindowInfo

# Two lines of OCR word data as pytesseract.image_to_data(output_type=Output.DICT)
# would return them: "Engine Driver" and "Spare engine" on separate lines, plus a
# blank/negative-confidence row (tesseract emits these for non-text regions) that
# must be skipped rather than grouped in.
_SAMPLE_DATA = {
    "text": ["Engine", "Driver", "", "Spare", "engine"],
    "conf": [95.0, 90.0, -1.0, 40.0, 60.0],
    "left": [10, 65, 0, 10, 60],
    "top": [10, 10, 0, 50, 50],
    "width": [50, 50, 0, 45, 55],
    "height": [20, 20, 0, 20, 20],
    "block_num": [1, 1, 1, 1, 1],
    "par_num": [1, 1, 1, 1, 1],
    "line_num": [1, 1, 1, 2, 2],
}


# Two unrelated icon-grid labels tesseract assigned the same line_num because
# they sit at the same y-coordinate, separated by a full column width (330px)
# rather than a normal inter-word gap -- the exact failure mode observed live
# ("Settings Whitelist Network Scheduler" merging into one unusable match).
_GRID_LABEL_DATA = {
    "text": ["Settings", "Whitelist"],
    "conf": [90.0, 88.0],
    "left": [50, 400],
    "top": [100, 100],
    "width": [70, 75],
    "height": [20, 20],
    "block_num": [1, 1],
    "par_num": [1, 1],
    "line_num": [1, 1],
}


def _make_image(tmp_path):
    path = tmp_path / "screenshot.png"
    PILImage.new("RGB", (200, 100), color="white").save(path)
    return path


def test_group_words_into_lines_joins_words_and_unions_bbox():
    lines = _group_words_into_lines(_SAMPLE_DATA)
    by_text = {line["text"]: line for line in lines}

    assert set(by_text) == {"Engine Driver", "Spare engine"}
    engine_driver = by_text["Engine Driver"]
    assert engine_driver["x"] == 10
    assert engine_driver["y"] == 10
    assert engine_driver["width"] == 105  # 65 + 50 - 10
    assert engine_driver["height"] == 20
    assert engine_driver["center_x"] == 62  # (10 + 115) // 2
    assert engine_driver["confidence"] == pytest.approx(92.5)


def test_group_words_into_lines_splits_on_large_horizontal_gap():
    lines = _group_words_into_lines(_GRID_LABEL_DATA)
    by_text = {line["text"]: line for line in lines}

    assert set(by_text) == {"Settings", "Whitelist"}
    settings = by_text["Settings"]
    assert settings["x"] == 50
    assert settings["width"] == 70
    assert settings["center_x"] == 85  # (50 + 120) // 2


def _build_mcp(monkeypatch, tmp_path):
    monkeypatch.setattr(pytesseract, "image_to_data", lambda image, output_type: _SAMPLE_DATA)
    config = ServerConfig(screenshot_dir=tmp_path, tesseract_path="tesseract")
    mcp = FastMCP("test")
    register_ocr_tools(mcp, config)
    return mcp


def test_find_text_matches_case_insensitive_by_default(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    result = asyncio.run(mcp.call_tool("find_text", {"path": str(image_path), "query": "driver"}))
    matches = result[1]["result"]

    assert len(matches) == 1
    assert matches[0]["text"] == "Engine Driver"
    assert matches[0]["center_x"] == 62
    assert matches[0]["center_y"] == 20


def test_find_text_sorts_multiple_matches_by_confidence_desc(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    result = asyncio.run(mcp.call_tool("find_text", {"path": str(image_path), "query": "engine"}))
    matches = result[1]["result"]

    assert [m["text"] for m in matches] == ["Engine Driver", "Spare engine"]


def test_find_text_case_sensitive_excludes_mismatched_case(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    result = asyncio.run(
        mcp.call_tool(
            "find_text", {"path": str(image_path), "query": "Engine", "case_sensitive": True}
        )
    )
    matches = result[1]["result"]

    assert [m["text"] for m in matches] == ["Engine Driver"]


def test_find_text_no_match_returns_empty_list(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    result = asyncio.run(
        mcp.call_tool("find_text", {"path": str(image_path), "query": "nonexistent"})
    )
    assert result[1]["result"] == []


def test_find_text_rejects_empty_query(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("find_text", {"path": str(image_path), "query": ""}))


def test_find_text_missing_file_raises(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("find_text", {"path": str(tmp_path / "nope.png"), "query": "x"}))


def test_find_text_non_image_file_raises(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    bogus = tmp_path / "not-an-image.png"
    bogus.write_text("not an image")

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("find_text", {"path": str(bogus), "query": "x"}))


def test_find_text_tesseract_not_found_raises_tool_error(monkeypatch, tmp_path):
    def raise_not_found(image, output_type):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", raise_not_found)
    config = ServerConfig(screenshot_dir=tmp_path, tesseract_path="tesseract")
    mcp = FastMCP("test")
    register_ocr_tools(mcp, config)
    image_path = _make_image(tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("find_text", {"path": str(image_path), "query": "x"}))


def test_read_screen_text_returns_all_lines_sorted_top_to_bottom(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    result = asyncio.run(mcp.call_tool("read_screen_text", {"path": str(image_path)}))
    lines = result[1]["result"]

    assert [line["text"] for line in lines] == ["Engine Driver", "Spare engine"]


def test_read_screen_text_captures_fresh_screenshot_when_no_path(monkeypatch, tmp_path):
    capture_calls = []
    image_path = _make_image(tmp_path)

    def fake_capture(config, mode, output_path):
        capture_calls.append((mode, output_path))
        return image_path

    mcp = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(ocr_module, "_capture_screenshot", fake_capture)

    asyncio.run(mcp.call_tool("read_screen_text", {}))

    assert capture_calls == [("full", None)]


def test_read_screen_text_uses_provided_path_without_capturing(monkeypatch, tmp_path):
    capture_calls = []

    def fake_capture(config, mode, output_path):
        capture_calls.append((mode, output_path))
        raise AssertionError("should not capture when a path is given")

    mcp = _build_mcp(monkeypatch, tmp_path)
    monkeypatch.setattr(ocr_module, "_capture_screenshot", fake_capture)
    image_path = _make_image(tmp_path)

    result = asyncio.run(mcp.call_tool("read_screen_text", {"path": str(image_path)}))

    assert capture_calls == []
    assert len(result[1]["result"]) == 2


def test_read_screen_text_missing_file_raises(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("read_screen_text", {"path": str(tmp_path / "nope.png")}))


def test_read_screen_text_tesseract_not_found_raises_tool_error(monkeypatch, tmp_path):
    def raise_not_found(image, output_type):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", raise_not_found)
    config = ServerConfig(screenshot_dir=tmp_path, tesseract_path="tesseract")
    mcp = FastMCP("test")
    register_ocr_tools(mcp, config)
    image_path = _make_image(tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("read_screen_text", {"path": str(image_path)}))


def _fake_window(x=40, y=20, width=100, height=60):
    return WindowInfo(
        id="{test-window}",
        title="Test",
        class_name="test.app",
        pid=1,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def _patch_window_scoping(monkeypatch, backend="kde", window=None, scale=1.0):
    monkeypatch.setattr(ocr_module, "_detect_backend", lambda config: backend)
    monkeypatch.setattr(
        ocr_module, "_kde_resolve_window_geometry", lambda config, w: window or _fake_window()
    )
    monkeypatch.setattr(ocr_module, "_get_display_scale", lambda config: scale)


def test_find_text_window_scoped_translates_coordinates_back_to_absolute(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)  # 200x100
    _patch_window_scoping(monkeypatch)

    result = asyncio.run(
        mcp.call_tool(
            "find_text", {"path": str(image_path), "query": "driver", "window": "{test-window}"}
        )
    )
    matches = result[1]["result"]

    assert len(matches) == 1
    # "Engine Driver" is at x=10/center_x=62 in the cropped image (_SAMPLE_DATA);
    # with the fake window's offset (40, 20) at scale 1.0, absolute coordinates
    # must be shifted by exactly that offset
    assert (matches[0]["x"], matches[0]["y"]) == (50, 30)
    assert (matches[0]["center_x"], matches[0]["center_y"]) == (102, 40)


def test_read_screen_text_window_scoped_translates_coordinates(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)
    _patch_window_scoping(monkeypatch)

    result = asyncio.run(
        mcp.call_tool("read_screen_text", {"path": str(image_path), "window": "{test-window}"})
    )
    lines = result[1]["result"]

    assert [line["text"] for line in lines] == ["Engine Driver", "Spare engine"]
    assert lines[0]["x"] == 50


def test_find_text_window_scoped_unsupported_on_wlroots(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)
    _patch_window_scoping(monkeypatch, backend="wlroots")

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "find_text",
                {"path": str(image_path), "query": "driver", "window": "{test-window}"},
            )
        )


def test_find_text_window_scoped_bounds_outside_screenshot_raises(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)  # 200x100
    _patch_window_scoping(monkeypatch, window=_fake_window(x=500, y=500, width=50, height=50))

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "find_text",
                {"path": str(image_path), "query": "driver", "window": "{test-window}"},
            )
        )


def test_find_text_without_window_never_resolves_window_geometry(monkeypatch, tmp_path):
    mcp = _build_mcp(monkeypatch, tmp_path)
    image_path = _make_image(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("must not resolve window geometry when window is not given")

    monkeypatch.setattr(ocr_module, "_detect_backend", fail)
    monkeypatch.setattr(ocr_module, "_kde_resolve_window_geometry", fail)

    result = asyncio.run(mcp.call_tool("find_text", {"path": str(image_path), "query": "driver"}))
    assert len(result[1]["result"]) == 1
