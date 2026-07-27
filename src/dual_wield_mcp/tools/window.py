import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 10

_POSITION_RE = re.compile(r"Position:\s*(-?[\d.]+),\s*(-?[\d.]+)")
_GEOMETRY_RE = re.compile(r"Geometry:\s*([\d.]+)x([\d.]+)")


@dataclass
class WindowInfo:
    id: str
    title: str
    class_name: str
    pid: int | None
    # position/size are in KWin's logical (HiDPI-scale-adjusted) pixels, which can
    # differ from the physical pixel space used by the screenshot and mouse tools
    x: float
    y: float
    width: float
    height: float


def _run(cmd: list[str]) -> str:
    # list-form argv (no shell=True) so window titles/ids can never be interpreted
    # as shell syntax
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT, check=False
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{cmd[0]} timed out after {_SUBPROCESS_TIMEOUT}s") from exc

    if result.returncode != 0:
        raise ToolError(f"{cmd[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


async def _run_async(cmd: list[str]) -> str:
    # async twin of _run, used only where callers issue several independent reads
    # they want to run concurrently (currently: per-window kdotool metadata lookups
    # in _kde_list_windows) -- not a wholesale replacement, since most tools here
    # only ever make one subprocess call and gain nothing from it
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_SUBPROCESS_TIMEOUT)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolError(f"{cmd[0]} timed out after {_SUBPROCESS_TIMEOUT}s") from exc

    if process.returncode != 0:
        stderr_text = stderr.decode().strip()
        stdout_text = stdout.decode().strip()
        raise ToolError(f"{cmd[0]} failed: {stderr_text or stdout_text}")
    return stdout.decode()


def _detect_backend(config: ServerConfig) -> str:
    if config.window_backend in ("kde", "wlroots"):
        return config.window_backend

    # Deliberately not gated on XDG_CURRENT_DESKTOP: MCP clients (including the
    # reference Python SDK's stdio_client) only pass a curated safe allowlist of
    # environment variables to the server subprocess by default (HOME, LOGNAME,
    # PATH, SHELL, TERM, USER) — XDG_CURRENT_DESKTOP is not among them, so checking
    # it here would misdetect on every real client launch, not just in tests that
    # happen to share the parent process's environment. Binary presence alone is
    # sufficient: kdotool is KDE-specific tooling, unlikely to be installed anywhere
    # that isn't KDE.
    if shutil.which(config.kdotool_path):
        return "kde"
    if shutil.which(config.wlrctl_path):
        return "wlroots"
    raise ToolError(
        "no supported window management backend found: need "
        f"'{config.kdotool_path}' on KDE Plasma, or '{config.wlrctl_path}' on other "
        "wlroots-based compositors"
    )


_KDOTOOL_METADATA_ARGS = [
    "getwindowname",
    "getwindowclassname",
    "getwindowgeometry",
    "getwindowpid",
]


def _kdotool_metadata_cmd(kdotool_path: str, window_id: str) -> list[str]:
    cmd = [kdotool_path]
    for arg in _KDOTOOL_METADATA_ARGS:
        cmd += [arg, window_id]
    return cmd


def _parse_kdotool_metadata(window_id: str, output: str) -> WindowInfo | None:
    # shared by the async (get_windows/get_active_window) and sync
    # (window-scoped OCR) metadata lookups below, so the parsing logic can't
    # drift between the two
    lines = output.split("\n")
    if len(lines) < 6:
        logger.warning("unexpected kdotool output for %s: %r", window_id, output)
        return None

    title, class_name = lines[0], lines[1]
    position_match = _POSITION_RE.search(lines[3])
    geometry_match = _GEOMETRY_RE.search(lines[4])
    x, y = (
        (float(position_match.group(1)), float(position_match.group(2)))
        if position_match
        else (0.0, 0.0)
    )
    width, height = (
        (float(geometry_match.group(1)), float(geometry_match.group(2)))
        if geometry_match
        else (0.0, 0.0)
    )
    pid_line = lines[5].strip()
    pid = int(pid_line) if pid_line.isdigit() else None

    return WindowInfo(
        id=window_id,
        title=title,
        class_name=class_name,
        pid=pid,
        x=x,
        y=y,
        width=width,
        height=height,
    )


async def _kde_get_window_metadata(config: ServerConfig, window_id: str) -> WindowInfo | None:
    output = await _run_async(_kdotool_metadata_cmd(config.kdotool_path, window_id))
    return _parse_kdotool_metadata(window_id, output)


def _kde_get_window_metadata_sync(config: ServerConfig, window_id: str) -> WindowInfo | None:
    # sync variant of the above, for callers outside an async context --
    # namely ocr.py's window-scoped find_text/read_screen_text/click_text
    output = _run(_kdotool_metadata_cmd(config.kdotool_path, window_id))
    return _parse_kdotool_metadata(window_id, output)


def _kde_resolve_window_geometry(config: ServerConfig, target: str) -> WindowInfo:
    # resolves a window id/title substring straight to full geometry in one
    # call, for callers that need physical bounds (window-scoped OCR) rather
    # than just a validated reference
    window_ref = _kde_resolve_window_ref(config, target)
    info = _kde_get_window_metadata_sync(config, window_ref)
    if info is None:
        raise ToolError(f"could not read geometry for window {target!r}")
    return info


def _kde_active_window_class(config: ServerConfig) -> str | None:
    # sync (not _run_async) variant of the active-window id + classname lookup,
    # for callers outside an async context -- namely input.py's opt-in
    # expected_window_class check on mouse_click/type_text
    window_id = _run([config.kdotool_path, "getactivewindow"]).strip()
    if not window_id:
        return None
    return _run([config.kdotool_path, "getwindowclassname", window_id]).strip() or None


async def _kde_get_active_window(config: ServerConfig) -> WindowInfo | None:
    window_id = (await _run_async([config.kdotool_path, "getactivewindow"])).strip()
    if not window_id:
        return None
    return await _kde_get_window_metadata(config, window_id)


async def _kde_list_windows(config: ServerConfig) -> list[WindowInfo]:
    ids_output = await _run_async([config.kdotool_path, "search", "."])
    window_ids = [line.strip() for line in ids_output.splitlines() if line.strip()]

    # per-window metadata lookups are independent reads -- fetched concurrently
    # instead of one kdotool spawn at a time, which dominated get_windows latency on
    # desktops with many open windows
    results = await asyncio.gather(
        *(_kde_get_window_metadata(config, window_id) for window_id in window_ids)
    )
    return [window for window in results if window is not None]


_WAIT_FOR_WINDOW_POLL_INTERVAL = 0.3


def _window_matches(window: WindowInfo, title: str | None, window_class: str | None) -> bool:
    title_ok = title is None or title.lower() in window.title.lower()
    class_ok = window_class is None or window.class_name == window_class
    return title_ok and class_ok


async def _kde_wait_for_window(
    config: ServerConfig, title: str | None, window_class: str | None, timeout: float
) -> WindowInfo:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        for window in await _kde_list_windows(config):
            if _window_matches(window, title, window_class):
                return window

        if loop.time() >= deadline:
            raise ToolError(
                f"no window matching title={title!r} class_name={window_class!r} "
                f"appeared within {timeout}s"
            )
        await asyncio.sleep(_WAIT_FOR_WINDOW_POLL_INTERVAL)


def _kde_resolve_window_ref(config: ServerConfig, target: str) -> str:
    # shared by every kdotool action below: accept either an exact {uuid} id
    # (from get_windows) or resolve a title substring via search
    if target.startswith("{") and target.endswith("}"):
        return target

    search_output = _run([config.kdotool_path, "search", "--limit", "1", re.escape(target)])
    found = [line.strip() for line in search_output.splitlines() if line.strip()]
    if not found:
        raise ToolError(f"no window matching {target!r}")
    return found[0]


def _kde_focus_window(config: ServerConfig, target: str) -> str:
    window_ref = _kde_resolve_window_ref(config, target)
    _run([config.kdotool_path, "windowactivate", window_ref])
    return window_ref


def _kde_close_window(config: ServerConfig, target: str) -> str:
    window_ref = _kde_resolve_window_ref(config, target)
    _run([config.kdotool_path, "windowclose", window_ref])
    return window_ref


def _kde_move_window(config: ServerConfig, target: str, x: int, y: int) -> str:
    window_ref = _kde_resolve_window_ref(config, target)
    _run([config.kdotool_path, "windowmove", window_ref, str(x), str(y)])
    return window_ref


def _kde_resize_window(config: ServerConfig, target: str, width: int, height: int) -> str:
    window_ref = _kde_resolve_window_ref(config, target)
    _run([config.kdotool_path, "windowsize", window_ref, str(width), str(height)])
    return window_ref


def _wlroots_focus_window(config: ServerConfig, target: str) -> None:
    # wlrctl's foreign-toplevel interface only supports matching/acting on windows,
    # not enumerating them, so there is no equivalent of the kdotool `{uuid}` path here
    _run([config.wlrctl_path, "toplevel", "focus", f"title:{target}"])


def register_window_tools(mcp: FastMCP, config: ServerConfig) -> None:
    # Detected once here rather than per tool call: the available backend doesn't
    # change during a server's lifetime under normal use, so there's no need to pay
    # for a fresh shutil.which() lookup (or two, on the wlroots fallback path) on
    # every get_windows/focus_window invocation.
    backend = _detect_backend(config)

    @mcp.tool()
    async def get_windows() -> list[dict]:
        """List visible windows with metadata (id, title, class, pid, position, size).

        position and size are in KWin's logical (HiDPI-scaled) pixels, not the
        physical pixels screenshot/mouse_move/mouse_click use — see this
        server's instructions for the conversion. Prefer focus_window over
        computing a click target from this geometry.

        Only supported on the KDE backend (via kdotool) — wlrctl's foreign-toplevel
        interface can match and act on windows but cannot enumerate them.
        """
        if backend != "kde":
            raise ToolError(
                "get_windows is not supported on the wlroots (wlrctl) backend: "
                "wlrctl can match and act on windows but has no window-listing command"
            )
        return [asdict(window) for window in await _kde_list_windows(config)]

    @mcp.tool()
    async def get_active_window() -> dict:
        """Get metadata for the currently focused (active) window.

        Same fields as get_windows: id, title, class_name, pid, position, and
        size (KWin logical pixels). Use this to confirm which window actually
        has focus right now before typing/pressing keys, instead of trusting
        an earlier get_windows/focus_window result — focus can change between
        calls, especially across any gap in a multi-step task.

        Only supported on the KDE backend (via kdotool) — wlrctl's
        foreign-toplevel interface can filter by an "active" state but has no
        direct query returning the active window's metadata.
        """
        if backend != "kde":
            raise ToolError(
                "get_active_window is not supported on the wlroots (wlrctl) backend: "
                "wlrctl has no direct query for the active window's metadata"
            )
        window = await _kde_get_active_window(config)
        if window is None:
            raise ToolError("no active window")
        return asdict(window)

    @mcp.tool()
    async def wait_for_window(
        title: str | None = None, window_class: str | None = None, timeout: float = 10.0
    ) -> dict:
        """Wait for a window matching a title substring and/or class to appear.

        Polls instead of guessing a fixed sleep duration, returning as soon as a
        match appears. Use this right after launch_app instead of a manual
        get_windows polling loop -- e.g. wait_for_window(window_class=
        "brave-browser") to get the new window's id as soon as it exists,
        without repeated round trips or a wait long enough to cover the worst
        case every time.

        Args:
            title: optional title substring to match (case-insensitive).
            window_class: optional exact class name to match (see get_windows).
                At least one of title/window_class must be given.
            timeout: seconds to wait before raising ToolError.

        Only supported on the KDE backend (via kdotool) -- wlrctl has a
        toplevel wait/waitfor action but no window-enumeration to build the
        returned metadata from.
        """
        if not title and not window_class:
            raise ToolError("at least one of title or window_class must be given")
        if timeout <= 0:
            raise ToolError("timeout must be positive")
        if backend != "kde":
            raise ToolError(
                "wait_for_window is not supported on the wlroots (wlrctl) backend: "
                "wlrctl has a toplevel wait action but no window-listing command to "
                "build metadata from"
            )

        window = await _kde_wait_for_window(config, title, window_class, timeout)
        return asdict(window)

    @mcp.tool()
    def focus_window(window: str) -> str:
        """Activate (focus and raise) a window.

        Args:
            window: on the KDE backend, either a window id from get_windows (e.g.
                "{uuid}") or a title substring to search for. On the wlroots backend,
                a title substring.
        """
        if not window:
            raise ToolError("window must not be empty")

        logger.info("focusing window %r via %s backend", window, backend)
        if backend == "kde":
            activated = _kde_focus_window(config, window)
            return f"activated {activated}"

        _wlroots_focus_window(config, window)
        return f"activated window matching title:{window}"

    @mcp.tool()
    def close_window(window: str) -> str:
        """Close a window.

        Args:
            window: a window id from get_windows (e.g. "{uuid}") or a title
                substring to search for.

        KDE backend only — wlrctl's foreign-toplevel interface has no close
        action (only minimize/maximize/fullscreen/focus/find/wait). Prefer this
        over a Bash `kill <pid>`: a never-before-seen pid always needs a fresh
        permission grant, while this tool only needs allowlisting once.
        """
        if not window:
            raise ToolError("window must not be empty")
        if backend != "kde":
            raise ToolError(
                "close_window is not supported on the wlroots (wlrctl) backend: "
                "wlrctl has no close action"
            )

        logger.info("closing window %r", window)
        closed = _kde_close_window(config, window)
        return f"closed {closed}"

    @mcp.tool()
    def move_window(window: str, x: int, y: int) -> str:
        """Move a window to a new position.

        Args:
            window: a window id from get_windows (e.g. "{uuid}") or a title
                substring to search for.
            x: target left edge, in KWin's logical (HiDPI-scaled) pixels — the
                same space get_windows reports, not the physical pixels
                screenshot/mouse_move/mouse_click use.
            y: target top edge, in logical pixels.

        KDE backend only — wlrctl has no move action. Prefer this over
        launching an application with a position flag (e.g. a browser's
        --window-position): Wayland does not let a client set its own absolute
        position, so such flags are silently ignored, but this goes through
        KWin's own scripting interface, which can place a window
        authoritatively.
        """
        if not window:
            raise ToolError("window must not be empty")
        if backend != "kde":
            raise ToolError(
                "move_window is not supported on the wlroots (wlrctl) backend: "
                "wlrctl has no move action"
            )

        logger.info("moving window %r to (%d, %d)", window, x, y)
        moved = _kde_move_window(config, window, x, y)
        return f"moved {moved} to ({x}, {y})"

    @mcp.tool()
    def resize_window(window: str, width: int, height: int) -> str:
        """Resize a window.

        Args:
            window: a window id from get_windows (e.g. "{uuid}") or a title
                substring to search for.
            width: target width, in KWin's logical (HiDPI-scaled) pixels — the
                same space get_windows reports, not the physical pixels
                screenshot/mouse_move/mouse_click use.
            height: target height, in logical pixels.

        KDE backend only — wlrctl has no resize action.
        """
        if width <= 0 or height <= 0:
            raise ToolError("width and height must be positive")
        if not window:
            raise ToolError("window must not be empty")
        if backend != "kde":
            raise ToolError(
                "resize_window is not supported on the wlroots (wlrctl) backend: "
                "wlrctl has no resize action"
            )

        logger.info("resizing window %r to %dx%d", window, width, height)
        resized = _kde_resize_window(config, window, width, height)
        return f"resized {resized} to {width}x{height}"
