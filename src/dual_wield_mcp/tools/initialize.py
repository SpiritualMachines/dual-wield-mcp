import logging
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.input import _get_display_scale, _get_display_size, _move_mouse_absolute
from dual_wield_mcp.tools.window import _detect_backend, _kde_list_windows

logger = logging.getLogger(__name__)


def _prewarm_mouse_calibration(config: ServerConfig) -> None:
    # mouse_move's closed-loop ratio calibration (input.py, _move_ratio_cache)
    # starts from an empirical default on every fresh server process and can
    # miss its intended target on the very first real move of a session
    # before self-correcting on later ones -- confirmed live, twice, in
    # separate test sessions (both runs landed the first click on the icon
    # to the left of the intended target). Two real moves to different
    # points, before any task-driven click depends on the calibration, let
    # it converge ahead of time instead of costing the first real click.
    # Just a mouse_move, not a click, so there is nothing to click safely --
    # a screen-center and off-center target are both fine regardless of
    # what's underneath them.
    width, height = _get_display_size(config)
    _move_mouse_absolute(config, width / 2, height / 2)
    _move_mouse_absolute(config, width / 4, height / 4)


def register_initialize_tool(mcp: FastMCP, config: ServerConfig) -> None:
    backend = _detect_backend(config)

    @mcp.tool()
    async def initialize() -> dict:
        """Call this once, as the first action in a new session, before any
        task-driven tool use.

        Pre-warms mouse_move's pointer calibration so the first real,
        task-driven click doesn't land off-target while it's still
        converging (see mouse_move's docstring for the closed-loop
        correction this warms up), and returns a snapshot of session-start
        desktop state so it doesn't need rediscovering reactively call by
        call: display scale, the detected window backend, and (KDE backend
        only) a fresh window listing.

        Returns:
            display_scale: the enabled display's HiDPI scale factor --
                physical = logical * display_scale (see get_windows).
            window_backend: "kde" or "wlroots", whichever this server
                detected and is using for window management tools.
            windows: fresh get_windows()-equivalent listing (same fields:
                id, title, class_name, pid, position, size, in KWin logical
                pixels), or null on the wlroots backend, which has no
                window-listing capability.
        """
        _prewarm_mouse_calibration(config)

        snapshot: dict = {
            "display_scale": _get_display_scale(config),
            "window_backend": backend,
            "windows": None,
        }
        if backend == "kde":
            snapshot["windows"] = [asdict(window) for window in await _kde_list_windows(config)]
        else:
            logger.info("initialize(): window listing skipped, unsupported on %s backend", backend)

        return snapshot
