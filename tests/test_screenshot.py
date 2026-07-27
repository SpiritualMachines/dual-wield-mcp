import asyncio
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent
from PIL import Image as PILImage

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.screenshot import register_screenshot_tool


def _build_mcp(monkeypatch, tmp_path, spectacle_writes_file=True):
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        if spectacle_writes_file:
            # -o <path> is always the last two args
            dest = cmd[-1]
            with open(dest, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr("dual_wield_mcp.tools.screenshot._run", fake_run)

    config = ServerConfig(screenshot_dir=tmp_path, spectacle_path="spectacle")
    mcp = FastMCP("test")
    register_screenshot_tool(mcp, config)
    return mcp, calls, config


def test_screenshot_returns_path_text_and_image(monkeypatch, tmp_path):
    mcp, _calls, config = _build_mcp(monkeypatch, tmp_path)

    result = asyncio.run(mcp.call_tool("screenshot", {}))

    assert len(result) == 2
    text_block, image_block = result
    assert isinstance(text_block, TextContent)
    assert isinstance(image_block, ImageContent)

    dest = config.screenshot_dir / text_block.text.split("/")[-1]
    assert text_block.text == str(dest)
    assert dest.exists()


def test_screenshot_path_text_matches_explicit_output_path(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)
    dest = tmp_path / "explicit.png"

    result = asyncio.run(mcp.call_tool("screenshot", {"output_path": str(dest)}))

    text_block = result[0]
    assert text_block.text == str(dest)


def test_screenshot_include_image_false_returns_only_path(monkeypatch, tmp_path):
    mcp, _calls, config = _build_mcp(monkeypatch, tmp_path)

    result = asyncio.run(mcp.call_tool("screenshot", {"include_image": False}))

    assert len(result) == 1
    (text_block,) = result
    assert isinstance(text_block, TextContent)
    dest = config.screenshot_dir / text_block.text.split("/")[-1]
    assert text_block.text == str(dest)
    assert dest.exists()


def test_screenshot_rejects_invalid_mode(monkeypatch, tmp_path):
    mcp, calls, _config = _build_mcp(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        asyncio.run(mcp.call_tool("screenshot", {"mode": "bogus"}))
    assert calls == []


def _make_source_image(tmp_path, width=100, height=80):
    src = tmp_path / "source.png"
    PILImage.new("RGB", (width, height), color=(10, 20, 30)).save(src)
    return src


def test_inspect_region_crops_and_returns_path_and_image(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)
    src = _make_source_image(tmp_path)

    result = asyncio.run(
        mcp.call_tool(
            "inspect_region", {"path": str(src), "x": 10, "y": 5, "width": 20, "height": 15}
        )
    )

    assert len(result) == 2
    text_block, image_block = result
    assert isinstance(text_block, TextContent)
    assert isinstance(image_block, ImageContent)

    dest = Path(text_block.text)
    assert dest.exists()
    with PILImage.open(dest) as cropped:
        assert cropped.size == (20, 15)


def test_inspect_region_respects_explicit_output_path(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)
    src = _make_source_image(tmp_path)
    dest = tmp_path / "cropped.png"

    result = asyncio.run(
        mcp.call_tool(
            "inspect_region",
            {"path": str(src), "x": 0, "y": 0, "width": 10, "height": 10, "output_path": str(dest)},
        )
    )

    assert result[0].text == str(dest)
    assert dest.exists()


def test_inspect_region_rejects_out_of_bounds(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)
    src = _make_source_image(tmp_path, width=100, height=80)

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "inspect_region", {"path": str(src), "x": 90, "y": 0, "width": 20, "height": 10}
            )
        )


def test_inspect_region_rejects_missing_file(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "inspect_region",
                {"path": str(tmp_path / "nope.png"), "x": 0, "y": 0, "width": 10, "height": 10},
            )
        )


def test_inspect_region_rejects_non_positive_dimensions(monkeypatch, tmp_path):
    mcp, _calls, _config = _build_mcp(monkeypatch, tmp_path)
    src = _make_source_image(tmp_path)

    with pytest.raises(ToolError):
        asyncio.run(
            mcp.call_tool(
                "inspect_region", {"path": str(src), "x": 0, "y": 0, "width": 0, "height": 10}
            )
        )
