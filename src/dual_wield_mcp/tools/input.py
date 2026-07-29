import json
import logging
import re
import subprocess
import time

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.keycodes import KEY_CODES
from dual_wield_mcp.tools.clipboard import _run_wl_copy
from dual_wield_mcp.tools.window import _detect_backend, _kde_active_window_class

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 10

# Above this length, type_text pastes via the clipboard instead of simulating
# keystrokes with ydotool type: strictly faster (one atomic paste vs. one
# ydotool call per character) and immune to the partial-type corruption a
# killed-on-timeout ydotool type can leave behind (see the timeout_hint
# below). Below it, per-character typing has no real downside and is left as
# the default so a short call never has an unannounced side effect on the
# clipboard. 100 chars is comfortably past "a short phrase" (the existing
# guidance's own dividing line) and, at ydotool's own documented ~40ms/char
# default (20ms key-delay + 20ms key-hold), comfortably within the flat
# _SUBPROCESS_TIMEOUT floor even in the worst case -- so text that still goes
# through the typing path never needs a longer, length-scaled timeout.
_TYPE_TEXT_PASTE_THRESHOLD = 100

# ydotool click button codes: low nibble selects the button, high nibble selects
# down/up/both (see `ydotool click --help`)
_BUTTON_CODES = {
    "left": 0x00,
    "right": 0x01,
    "middle": 0x02,
    "side": 0x03,
    "extra": 0x04,
    "forward": 0x05,
    "back": 0x06,
    "task": 0x07,
}
_CLICK_DOWN_AND_UP = 0xC0

# Delay between the two clicks of a double-click, issued within one mouse_click
# call. Two separate mouse_click tool calls do not reliably register as a
# double-click: the MCP round trip between them (a fresh subprocess spawn plus
# tool dispatch) runs longer than the desktop's double-click timing threshold,
# confirmed live -- two sequential calls landed as two independent single
# clicks (a select, then a no-op reselect) rather than an open action. This
# value is comfortably under typical desktop thresholds (commonly 200-500ms)
# while still being two distinct press/release pairs.
_DOUBLE_CLICK_INTERVAL = 0.1

# ydotool's `mousemove --absolute` does not work against KWin on this compositor
# (confirmed empirically: the cursor stays pinned near the origin regardless of the
# target coordinates given). Relative movement does work, but KDE's pointer
# acceleration curve distorts it by a large, non-1:1 factor (observed ~2.3x for a
# single large synthetic jump). So mouse_move closes the loop instead: move
# relatively, measure the actual resulting position via `kdotool getmouselocation`
# (which reports KWin's logical/HiDPI-scaled pixels, converted here to the physical
# pixels used by screenshot/click coordinates via the scale from `kscreen-doctor`),
# and correct iteratively until within tolerance.
_MOUSE_MOVE_TOLERANCE = 3.0
_MOUSE_MOVE_MAX_ITERATIONS = 6
_INITIAL_MOVE_RATIO = 2.33  # empirically observed physical-px moved per ydotool unit

_MOUSE_LOCATION_RE = re.compile(r"x:(-?\d+)\s+y:(-?\d+)")

# Display scale does not change during a server's lifetime under normal use, so it's
# fetched once per kscreen-doctor binary and reused rather than re-queried on every
# mouse_move call. Keyed by path (not a single global) so a config pointing at a
# different binary isn't served a stale value from another config.
_display_scale_cache: dict[str, float] = {}

# Physical panel resolution (pixels) of the enabled display -- same
# subprocess and JSON payload _get_display_scale reads, but a different
# field, and cached separately since the two are read independently by
# different callers with no shared plumbing between them worth adding for
# two lookups.
_display_size_cache: dict[str, tuple[float, float]] = {}

# The calibrated move ratio learned by closed-loop correction reflects the host's
# pointer-acceleration curve, not anything specific to one mouse_move call, so it's
# kept across calls (keyed by ydotool path) instead of resetting to the empirical
# _INITIAL_MOVE_RATIO guess every time. After the first mouse_move on a given host,
# later calls typically start from an already-accurate ratio and converge in 1-2
# iterations instead of up to _MOUSE_MOVE_MAX_ITERATIONS.
_move_ratio_cache: dict[str, tuple[float, float]] = {}


def _run(
    cmd: list[str], timeout: float = _SUBPROCESS_TIMEOUT, timeout_hint: str | None = None
) -> str:
    # list-form argv (no shell=True) so key/text content can never be interpreted
    # as shell syntax
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        hint = f" -- {timeout_hint}" if timeout_hint else ""
        raise ToolError(f"{cmd[0]} timed out after {timeout}s{hint}") from exc

    if result.returncode != 0:
        raise ToolError(f"{cmd[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _resolve_key(name: str) -> int:
    code = KEY_CODES.get(name.strip().lower())
    if code is None:
        raise ToolError(f"unknown key name: {name!r}")
    return code


def _get_display_scale(config: ServerConfig) -> float:
    cached = _display_scale_cache.get(config.kscreen_doctor_path)
    if cached is not None:
        return cached

    raw = _run([config.kscreen_doctor_path, "-j", "-o"])
    try:
        # kscreen-doctor can print trailing data after the JSON object; only the
        # first object is needed
        data, _ = json.JSONDecoder().raw_decode(raw)
        for output in data["outputs"]:
            if output.get("enabled"):
                scale = float(output["scale"])
                _display_scale_cache[config.kscreen_doctor_path] = scale
                return scale
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ToolError(f"could not determine display scale: {exc}") from exc
    raise ToolError("kscreen-doctor reported no enabled outputs")


def _get_display_size(config: ServerConfig) -> tuple[float, float]:
    # output["size"] is the panel's native resolution in physical pixels --
    # the same space screenshot/mouse_move/mouse_click use -- as opposed to
    # kscreen-doctor's separate "screen.currentSize", which is the
    # HiDPI-scaled logical desktop size get_windows/move_window/
    # resize_window use.
    cached = _display_size_cache.get(config.kscreen_doctor_path)
    if cached is not None:
        return cached

    raw = _run([config.kscreen_doctor_path, "-j", "-o"])
    try:
        data, _ = json.JSONDecoder().raw_decode(raw)
        for output in data["outputs"]:
            if output.get("enabled"):
                size = output["size"]
                width, height = float(size["width"]), float(size["height"])
                _display_size_cache[config.kscreen_doctor_path] = (width, height)
                return (width, height)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ToolError(f"could not determine display size: {exc}") from exc
    raise ToolError("kscreen-doctor reported no enabled outputs")


def _get_cursor_position(config: ServerConfig, scale: float) -> tuple[float, float]:
    output = _run([config.kdotool_path, "getmouselocation"])
    match = _MOUSE_LOCATION_RE.search(output)
    if not match:
        raise ToolError(f"could not parse cursor position from kdotool output: {output!r}")
    logical_x, logical_y = float(match.group(1)), float(match.group(2))
    return logical_x * scale, logical_y * scale


def _move_mouse_absolute(config: ServerConfig, target_x: float, target_y: float) -> None:
    scale = _get_display_scale(config)
    ratio_x, ratio_y = _move_ratio_cache.get(
        config.ydotool_path, (_INITIAL_MOVE_RATIO, _INITIAL_MOVE_RATIO)
    )

    try:
        for _ in range(_MOUSE_MOVE_MAX_ITERATIONS):
            current_x, current_y = _get_cursor_position(config, scale)
            error_x = target_x - current_x
            error_y = target_y - current_y
            if abs(error_x) <= _MOUSE_MOVE_TOLERANCE and abs(error_y) <= _MOUSE_MOVE_TOLERANCE:
                return

            move_x = round(error_x / ratio_x)
            move_y = round(error_y / ratio_y)
            if move_x == 0:
                move_x = 1 if error_x > 0 else -1
            if move_y == 0:
                move_y = 1 if error_y > 0 else -1

            # "--" prevents negative deltas (e.g. "-813") from being parsed as options
            _run([config.ydotool_path, "mousemove", "--", str(move_x), str(move_y)])

            new_x, new_y = _get_cursor_position(config, scale)
            actual_dx, actual_dy = new_x - current_x, new_y - current_y
            # refine the ratio from what actually happened, guarding against div-by-zero
            # and against a wild reading destabilizing the next iteration
            if move_x != 0 and actual_dx != 0:
                candidate = actual_dx / move_x
                if 0.1 <= candidate <= 20:
                    ratio_x = candidate
            if move_y != 0 and actual_dy != 0:
                candidate = actual_dy / move_y
                if 0.1 <= candidate <= 20:
                    ratio_y = candidate

        logger.warning(
            "mouse_move did not converge within tolerance after %d iterations",
            _MOUSE_MOVE_MAX_ITERATIONS,
        )
    finally:
        # persist whatever was learned even on early return or a failed convergence,
        # so the next call benefits from it
        _move_ratio_cache[config.ydotool_path] = (ratio_x, ratio_y)


def _check_expected_window(config: ServerConfig, expected_window_class: str | None) -> None:
    # backend is detected lazily, only when a caller actually opts into this check --
    # not at registration, so input-only setups with no window backend installed at
    # all (kdotool/wlrctl) are unaffected unless they use this parameter
    if expected_window_class is None:
        return

    backend = _detect_backend(config)
    if backend != "kde":
        raise ToolError(
            "expected_window_class verification is not supported on the wlroots "
            "(wlrctl) backend: wlrctl has no query for the active window's class"
        )

    actual = _kde_active_window_class(config)
    if actual != expected_window_class:
        raise ToolError(
            f"expected focused window class {expected_window_class!r}, but the "
            f"currently focused window is {actual!r} -- refusing to act on a "
            "possibly stale target"
        )


def _paste_via_clipboard(config: ServerConfig, text: str) -> None:
    # shared by type_text's long-text fallback and the standalone paste_text
    # tool (tools/paste_text.py), so the two never drift out of sync
    _run_wl_copy([config.wl_copy_path], text)

    codes = [_resolve_key(name) for name in ("ctrl", "v")]
    down = [f"{code}:1" for code in codes]
    up = [f"{code}:0" for code in reversed(codes)]
    _run([config.ydotool_path, "key", *down, *up])


def register_input_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def mouse_move(x: int, y: int, space: str = "physical") -> str:
        """Move the mouse pointer to an absolute screen position.

        Coordinates default to physical pixels, the same space screenshot
        images use. get_windows/move_window/resize_window instead report
        position/size in logical (HiDPI-scaled) pixels — pass space="logical"
        to give get_windows-style coordinates directly and let this tool do
        the physical = logical * scale conversion, instead of computing it by
        hand. This does not remove the need to verify visually: window
        position can still settle or animate after the geometry was read,
        independent of scale, so prefer a fresh screenshot for anything
        precise (e.g. clicking a specific small target).

        Args:
            x: target X coordinate (0 is the left edge)
            y: target Y coordinate (0 is the top edge)
            space: "physical" (default) or "logical" — which pixel space x/y
                are given in.
        """
        if space not in ("physical", "logical"):
            raise ToolError('space must be "physical" or "logical"')
        if x < 0 or y < 0:
            raise ToolError("x and y must be non-negative")

        target_x, target_y = float(x), float(y)
        if space == "logical":
            scale = _get_display_scale(config)
            target_x *= scale
            target_y *= scale

        logger.info("moving mouse to (%d, %d) [%s]", x, y, space)
        _move_mouse_absolute(config, target_x, target_y)
        return f"moved pointer to ({x}, {y}) [{space}]"

    @mcp.tool()
    def mouse_click(
        button: str = "left",
        x: int | None = None,
        y: int | None = None,
        space: str = "physical",
        expected_window_class: str | None = None,
        double: bool = False,
    ) -> str:
        """Click a mouse button, optionally moving the pointer there first.

        Args:
            button: one of left, right, middle, side, extra, forward, back, task
            x: optional target X coordinate. If given (together with y), the
                pointer is moved there first via the same closed-loop
                correction mouse_move uses, then clicked -- all within this
                one call. A separate mouse_move followed by mouse_click
                leaves a full MCP round trip between the move finishing and
                the click firing, which is real time for the user's own live
                mouse movement to land in; combining them here removes that
                gap for the manual-coordinate case (click_text already does
                this internally for OCR-found targets). Omit both x and y to
                click wherever the pointer already is.
            y: optional target Y coordinate. Must be given together with x.
            space: "physical" (default) or "logical" -- which pixel space x/y
                are given in, same meaning as mouse_move's space parameter.
                Ignored if x/y are omitted.
            expected_window_class: optional. If given, verify the currently
                focused window's class matches before clicking, raising
                ToolError on a mismatch instead of clicking into a possibly
                stale target. Get a window's class from get_windows or
                get_active_window. KDE backend only. Checked once,
                immediately before the click (after any move); clicking can
                itself legitimately change focus (e.g. a click opening a new
                dialog), so this is not re-checked after.
            double: if True, click twice in quick succession within this one
                call to register as a double-click -- e.g. to open a file or
                folder in a list/icon view configured for double-click-to-open.
                Two separate mouse_click calls do not reliably work for this:
                the round trip between them is slower than the desktop's
                double-click timing threshold, confirmed live. Prefer a single
                click plus focus_window plus key_press("enter") over this for
                opening a selected item where that's an option -- it's the
                more broadly reliable pattern; use double=True when the target
                has no keyboard-activation equivalent.
        """
        button_code = _BUTTON_CODES.get(button.strip().lower())
        if button_code is None:
            raise ToolError(f"unknown button: {button!r}")
        if space not in ("physical", "logical"):
            raise ToolError('space must be "physical" or "logical"')
        if (x is None) != (y is None):
            raise ToolError("x and y must be given together")

        if x is not None:
            if x < 0 or y < 0:
                raise ToolError("x and y must be non-negative")

            target_x, target_y = float(x), float(y)
            if space == "logical":
                scale = _get_display_scale(config)
                target_x *= scale
                target_y *= scale

            logger.info("moving mouse to (%d, %d) [%s] before clicking", x, y, space)
            _move_mouse_absolute(config, target_x, target_y)

        _check_expected_window(config, expected_window_class)

        click_byte = _CLICK_DOWN_AND_UP | button_code
        cmd = [config.ydotool_path, "click", f"0x{click_byte:02x}"]
        logger.info("clicking mouse: %s", cmd)
        _run(cmd)
        if double:
            time.sleep(_DOUBLE_CLICK_INTERVAL)
            _run(cmd)
            return f"double-clicked {button}"
        return f"clicked {button}"

    @mcp.tool()
    def key_press(keys: str) -> str:
        """Press a key or key combination.

        Args:
            keys: a single key name (e.g. "enter", "f5") or a '+'-joined combination
                (e.g. "ctrl+c", "ctrl+shift+t"). All keys are pressed down together,
                then released in reverse order.
        """
        names = [name for name in keys.split("+") if name]
        if not names:
            raise ToolError("no keys specified")

        codes = [_resolve_key(name) for name in names]
        down = [f"{code}:1" for code in codes]
        up = [f"{code}:0" for code in reversed(codes)]
        cmd = [config.ydotool_path, "key", *down, *up]
        logger.info("pressing keys: %s", cmd)
        _run(cmd)
        return f"pressed {keys}"

    @mcp.tool()
    def type_text(text: str, expected_window_class: str | None = None) -> str:
        """Type a literal text string via the keyboard.

        Text longer than 100 characters is pasted via the clipboard instead
        of typed -- a single atomic paste rather than one simulated keystroke
        per character, and immune to the partial-text corruption a
        killed-on-timeout ydotool type can otherwise leave behind. This
        overwrites the current clipboard contents; use clipboard_get first if
        you need to restore it afterward. Text at or under 100 characters is
        still typed via ydotool, with no clipboard side effect.

        Args:
            text: the string to type or paste. Above the 100-character
                threshold, pasting is effectively instant regardless of
                length. At or under the threshold, real per-character
                keystroke simulation stays comfortably within the default
                timeout at any length this short.
            expected_window_class: optional. If given, verify the currently
                focused window's class matches both before and after typing
                or pasting, raising ToolError on a mismatch instead of
                trusting the text landed in the intended window. Get a
                window's class from get_windows or get_active_window. KDE
                backend only. Checked on both sides (unlike mouse_click)
                because typing/pasting normally should not itself change
                focus, so a post-check can catch the user switching windows
                (e.g. alt-tabbing) partway through.
        """
        if not text:
            raise ToolError("text must not be empty")

        _check_expected_window(config, expected_window_class)

        if len(text) > _TYPE_TEXT_PASTE_THRESHOLD:
            logger.info(
                "text length %d exceeds paste threshold (%d), pasting via clipboard "
                "instead of typing",
                len(text),
                _TYPE_TEXT_PASTE_THRESHOLD,
            )
            _paste_via_clipboard(config, text)
            _check_expected_window(config, expected_window_class)
            return f"pasted {len(text)} characters via clipboard"

        cmd = [config.ydotool_path, "type", "--", text]
        logger.info("typing text (%d chars)", len(text))
        _run(
            cmd,
            timeout_hint=(
                "ydotool was killed mid-keystream, so partial text may already be in "
                "the focused window -- check the target and undo/fix before retrying "
                "rather than re-typing on top of it"
            ),
        )

        _check_expected_window(config, expected_window_class)
        return f"typed {len(text)} characters"
