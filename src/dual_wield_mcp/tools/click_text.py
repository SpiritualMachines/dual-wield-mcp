import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.input import (
    _BUTTON_CODES,
    _CLICK_DOWN_AND_UP,
    _check_expected_window,
    _move_mouse_absolute,
)
from dual_wield_mcp.tools.input import _run as _ydotool_run
from dual_wield_mcp.tools.ocr import _find_text_in_image, _find_text_in_window
from dual_wield_mcp.tools.screenshot import _capture_screenshot

logger = logging.getLogger(__name__)


def register_click_text_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def click_text(
        query: str,
        path: str | None = None,
        case_sensitive: bool = False,
        button: str = "left",
        expected_window_class: str | None = None,
        window: str | None = None,
    ) -> str:
        """Find text on screen via OCR and click it, in one server-side call.

        Combines screenshot + find_text + mouse_move + mouse_click into a
        single tool call: takes a fresh full-desktop screenshot if path is not
        given, locates query with the same OCR/grouping logic as find_text,
        and -- only when there is exactly one match -- moves the pointer to
        its center and clicks. No image is sent to the calling agent for this
        path, and there is no gap between locating the target and acting on
        it for the desktop to change in, unlike a manual screenshot ->
        find_text -> mouse_move -> mouse_click sequence.

        Ambiguity is refused rather than guessed at: zero matches or more
        than one match both raise ToolError describing what was found,
        instead of picking one. Fall back to find_text plus a screenshot/
        inspect_region visual check to disambiguate in that case -- the same
        judgment call a manual click would need. A single match acts
        regardless of its OCR confidence score, which the returned message
        still reports -- confidence has been shown, live, to be an unreliable
        proxy for correctness in both directions (a real match scoring as low
        as 37 percent; a genuine misread scoring 87 percent), so it is
        informational here rather than a second gate on top of the ambiguity
        check.

        Args:
            query: substring to search for, same semantics as find_text.
            path: optional path to an existing screenshot, typically a prior
                screenshot call's returned path. Captures a fresh full-desktop
                screenshot if omitted.
            case_sensitive: if False (default), matching ignores case.
            button: one of left, right, middle, side, extra, forward, back, task.
            expected_window_class: optional, same semantics as mouse_click's
                parameter -- verified immediately before clicking (KDE
                backend only).
            window: optional window id (from get_windows) or title substring,
                same semantics as find_text's parameter -- scopes OCR to that
                window's region so text elsewhere on the desktop (most
                commonly the calling agent's own visible terminal) can't
                produce a false match or, worse, silently merge with the
                target window's real text and shift the click point outside
                it. Prefer this whenever the query text could plausibly
                appear anywhere else on screen. KDE backend only.
        """
        button_code = _BUTTON_CODES.get(button.strip().lower())
        if button_code is None:
            raise ToolError(f"unknown button: {button!r}")

        image_path = path if path is not None else str(_capture_screenshot(config, "full", None))

        if window is not None:
            matches = _find_text_in_window(image_path, query, case_sensitive, config, window)
        else:
            matches = _find_text_in_image(image_path, query, case_sensitive, config.tesseract_path)

        if not matches:
            raise ToolError(f"no match for {query!r} in {image_path}")
        if len(matches) > 1:
            found = [m["text"] for m in matches]
            raise ToolError(
                f"{len(matches)} matches for {query!r} in {image_path}, refusing to "
                f"guess which to click: {found}. Use find_text plus a visual check to "
                "disambiguate."
            )

        match = matches[0]
        _check_expected_window(config, expected_window_class)

        logger.info(
            "click_text(%r): clicking %r at (%d, %d) confidence=%.1f",
            query,
            match["text"],
            match["center_x"],
            match["center_y"],
            match["confidence"],
        )
        _move_mouse_absolute(config, float(match["center_x"]), float(match["center_y"]))
        click_byte = _CLICK_DOWN_AND_UP | button_code
        _ydotool_run([config.ydotool_path, "click", f"0x{click_byte:02x}"])

        return (
            f"clicked {button} on {match['text']!r} at "
            f"({match['center_x']}, {match['center_y']}) "
            f"[confidence {match['confidence']:.1f}]"
        )
