import logging
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from dual_wield_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_FULL_CAPTURE_TIMEOUT = 30
# region capture waits on an interactive on-screen selection, so it needs more headroom
_REGION_CAPTURE_TIMEOUT = 120


def _run(cmd: list[str], timeout: int) -> None:
    # list-form argv (no shell=True) so configured paths can never be interpreted
    # as shell syntax
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{cmd[0]} timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise ToolError(f"{cmd[0]} failed: {result.stderr.strip()}")


def _capture_screenshot(config: ServerConfig, mode: str, output_path: str | None) -> Path:
    # shared by the screenshot tool below and click_text.py, so a caller that
    # only needs a fresh image to hand to find_text can capture one without
    # going through the tool wrapper (and its Image return) at all
    if mode not in ("full", "region"):
        raise ToolError('mode must be "full" or "region"')

    if output_path is not None:
        dest = Path(output_path).expanduser()
    else:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        dest = config.screenshot_dir / f"screenshot-{timestamp}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    region_flag = "-r" if mode == "region" else "-f"
    timeout = _REGION_CAPTURE_TIMEOUT if mode == "region" else _FULL_CAPTURE_TIMEOUT
    cmd = [config.spectacle_path, "-b", "-n", region_flag, "-o", str(dest)]

    logger.info("capturing screenshot: %s", cmd)
    _run(cmd, timeout)

    if not dest.exists():
        raise ToolError(f"spectacle did not produce an output file at {dest}")
    return dest


def register_screenshot_tool(mcp: FastMCP, config: ServerConfig) -> None:
    # structured_output=False: the return type mixes str and Image, which pydantic
    # cannot build a structured-output schema for (Image has no pydantic-core schema)
    @mcp.tool(structured_output=False)
    def screenshot(
        mode: str = "full", output_path: str | None = None, include_image: bool = True
    ) -> list[str | Image]:
        """Capture the KDE Plasma desktop via spectacle.

        The returned image is at the display's physical pixel resolution — the
        same coordinate space mouse_move and mouse_click use. This differs from
        get_windows, which reports position/size in logical (HiDPI-scaled)
        pixels; see this server's instructions for the conversion.

        Returns the saved file's absolute path as text, followed by the image
        itself — the path lets a caller reference this exact screenshot later
        (e.g. for region inspection) without having to rediscover it.

        Args:
            mode: "full" to capture the entire desktop, "region" to interactively
                select an area first (on-screen drag selection).
            output_path: optional destination file path. Defaults to a timestamped
                file under the configured screenshot directory.
            include_image: if False, return only the saved path as text, skipping
                the image content entirely. Use this when the screenshot is only
                needed as input to find_text/click_text and will not be viewed
                directly — it avoids sending the image for vision processing when
                nothing is going to look at it.
        """
        dest = _capture_screenshot(config, mode, output_path)
        if not include_image:
            return [str(dest)]
        return [str(dest), Image(path=str(dest))]

    # structured_output=False: same reason as screenshot above
    @mcp.tool(structured_output=False)
    def inspect_region(
        path: str,
        x: int,
        y: int,
        width: int,
        height: int,
        output_path: str | None = None,
    ) -> list[str | Image]:
        """Crop a rectangular region out of an existing screenshot for close-up inspection.

        Use this to verify a click target or read small text/icons at native
        resolution instead of shelling out to image tools like magick/identify —
        their commands typically need dynamic file-path discovery, which Claude
        Code cannot statically analyze and will re-prompt for on every call
        regardless of any allowlist entry; this tool is a single schema-validated
        call instead.

        x, y, width, and height are in the same physical-pixel space as
        screenshot's output (and mouse_move/mouse_click) — not get_windows'
        logical pixels.

        Args:
            path: path to an existing image file, typically a prior screenshot
                call's returned path.
            x: left edge of the region, in pixels.
            y: top edge of the region, in pixels.
            width: region width in pixels.
            height: region height in pixels.
            output_path: optional destination for the cropped image. Defaults to
                a file named after the source with the region embedded, saved
                alongside the source.
        """
        if width <= 0 or height <= 0:
            raise ToolError("width and height must be positive")
        if x < 0 or y < 0:
            raise ToolError("x and y must be non-negative")

        src = Path(path).expanduser()
        if not src.is_file():
            raise ToolError(f"no such file: {src}")

        try:
            image = PILImage.open(src)
        except UnidentifiedImageError as exc:
            raise ToolError(f"{src} is not a readable image: {exc}") from exc

        img_width, img_height = image.size
        if x + width > img_width or y + height > img_height:
            raise ToolError(
                f"region ({x},{y},{width}x{height}) exceeds image bounds ({img_width}x{img_height})"
            )

        if output_path is not None:
            dest = Path(output_path).expanduser()
        else:
            dest = src.with_name(f"{src.stem}-region-{x}-{y}-{width}x{height}{src.suffix}")
        dest.parent.mkdir(parents=True, exist_ok=True)

        cropped = image.crop((x, y, x + width, y + height))
        cropped.save(dest)

        return [str(dest), Image(path=str(dest))]
