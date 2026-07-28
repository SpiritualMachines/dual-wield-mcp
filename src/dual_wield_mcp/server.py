import logging
import os

from mcp.server.fastmcp import FastMCP

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.app import register_app_tools
from dual_wield_mcp.tools.click_text import register_click_text_tools
from dual_wield_mcp.tools.clipboard import register_clipboard_tools
from dual_wield_mcp.tools.initialize import register_initialize_tool
from dual_wield_mcp.tools.input import register_input_tools
from dual_wield_mcp.tools.ocr import register_ocr_tools
from dual_wield_mcp.tools.paste_text import register_paste_text_tools
from dual_wield_mcp.tools.screenshot import register_screenshot_tool
from dual_wield_mcp.tools.window import register_window_tools

logger = logging.getLogger(__name__)


def _ensure_session_environment() -> None:
    """Fill in standard Wayland/DBus session variables if missing.

    MCP clients (including the reference Python SDK's stdio_client) only pass a
    curated safe allowlist of environment variables to the server subprocess by
    default (HOME, LOGNAME, PATH, SHELL, TERM, USER) — WAYLAND_DISPLAY,
    DBUS_SESSION_BUS_ADDRESS, and XDG_RUNTIME_DIR are not among them, so every tool
    here (spectacle, kdotool, ydotool) fails without them. Fill in the standard
    systemd-user-session values when absent, since a client may not offer a way to
    configure the subprocess environment.
    """
    runtime_dir = os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")


_INSTRUCTIONS = """\
Call initialize() once, as the very first action in a new session, before any
task-driven tool use. It pre-warms mouse_move's pointer calibration (the
first real click of a fresh session can otherwise land off-target while that
calibration is still converging) and returns a snapshot of session-start
desktop state -- display scale, detected window backend, and a fresh window
listing -- so that doesn't need rediscovering reactively call by call.

Two different pixel spaces are in play; mixing them up produces off-target
clicks. `get_windows` reports window position/size in KWin's logical
(HiDPI-scale-adjusted) pixels. `screenshot`, `mouse_move`, and `mouse_click` all
operate in physical pixels. Convert with physical = logical * scale, where
scale is the "scale" field of the enabled output from `kscreen-doctor -j -o`.

Do not compute a click target from get_windows geometry alone: take a
screenshot first and verify the target pixel visually, since window position
can also settle or animate after the geometry was read, independent of scale.

Call focus_window before key_press/type_text on a specific window: synthetic
(uinput-driven) clicks do not reliably transfer KWin keyboard focus, even when
the click itself lands correctly.

Launch applications with launch_app, not a shell command, and position them
with move_window/resize_window afterward, not a command-line position/size
flag: Wayland does not let a client set its own absolute position, so a flag
like a browser's --window-position is silently ignored, while move_window/
resize_window go through KWin's own scripting interface and take effect for
real. Use close_window to close a window rather than killing its process.

After launch_app, prefer wait_for_window over a manual get_windows polling
loop or a fixed sleep — it returns as soon as a matching window appears.

For pasting long or special-character strings (URLs, search queries), prefer
paste_text over type_text: it sets the clipboard and pastes via ctrl+v in one
server-side call, atomic instead of simulated per-character typing. Use
clipboard_set plus a separate key_press("ctrl+v") only when the clipboard
needs to be set without pasting immediately.

To click a specific labeled button, link, or menu item, prefer click_text over
a manual screenshot -> find_text -> mouse_move -> mouse_click sequence: it does
all four in one server-side call, with no image sent back for review, when
there is exactly one confident match. It refuses (ToolError) rather than
guess on zero, multiple, or low-confidence matches -- fall back to find_text on
a screenshot (pass include_image=False if the picture itself isn't needed)
plus a visual check via inspect_region only in that ambiguous case. find_text
returns a center point in the same physical-pixel space mouse_move uses.
mouse_move also accepts space="logical" to take get_windows-style coordinates
directly, skipping the manual physical = logical * scale conversion above.

To read an entire board, grid, or list of text at once (e.g. every revealed
number in a puzzle game, or every row of a file list), prefer read_screen_text
over several find_text calls or eyeballing inspect_region crops one at a
time: it returns every detected line and position in a single call.

find_text/read_screen_text/click_text accept an optional window parameter (a
window id from get_windows, or a title substring): when given, OCR runs only
against that window's region and returned coordinates are still absolute
physical pixels. Use this whenever the query text could plausibly appear
elsewhere on the desktop too -- most commonly your own visible terminal,
which routinely echoes back the exact text you are about to search for.
Without scoping, OCR can merge real text from the target window with
unrelated text from a different window into one line, silently shifting a
match's center point off target rather than cleanly refusing -- worse than
the zero/multiple-match refusal case, since it can produce exactly one
wrong match. Note window scoping is not automatically better for
read_screen_text's bulk-reading use: cropping can occasionally cause
tesseract to miss stylized or hyperlink-styled text it would find with
full-page context, so prefer scoping when disambiguating a click target and
prefer an unscoped read when completeness matters more.

A launched app's window class does not always match its launch command
(e.g. kwrite launches as org.kde.kwrite) -- check get_windows once if
wait_for_window's window_class guess doesn't match, rather than guessing
repeatedly and wasting the timeout.

mouse_click accepts double=True to double-click within one call. Two
separate mouse_click calls do not reliably register as a double-click: the
round trip between them is slower than the desktop's double-click timing
threshold. Prefer a single click plus focus_window plus key_press("enter")
over double=True when the target has a keyboard-activation equivalent --
double=True is for when it doesn't.

mouse_click also accepts optional x/y/space to move the pointer there first
and click in one call, same as click_text already does internally for
OCR-found targets -- prefer this over a separate mouse_move then mouse_click
for a manually-computed coordinate (e.g. read off an inspect_region crop):
it removes the MCP round trip between the move finishing and the click
firing, which is real time the user's own live mouse movement could land
in.

If tool calls are hitting individual first-use permission prompts scattered
through a session rather than resolved upfront, that's a client-side config
gap, not something to work around mid-task: recommend the user pre-approve
every dual-wield-mcp tool at once in their client's permission config (e.g.
Claude Code's .claude/settings.json permissions.allow, one
mcp__dual-wield__<tool> entry per tool) instead of clearing prompts one at a
time as they come up. Confirmed live to eliminate the scattered-prompt
problem entirely, with no server-side change needed.
"""


def build_server(config: ServerConfig) -> FastMCP:
    mcp = FastMCP("dual-wield-mcp", instructions=_INSTRUCTIONS)
    register_initialize_tool(mcp, config)
    register_screenshot_tool(mcp, config)
    register_input_tools(mcp, config)
    register_window_tools(mcp, config)
    register_app_tools(mcp, config)
    register_clipboard_tools(mcp, config)
    register_paste_text_tools(mcp, config)
    register_ocr_tools(mcp, config)
    register_click_text_tools(mcp, config)
    return mcp


def main() -> None:
    _ensure_session_environment()

    config = ServerConfig.from_env()
    logging.basicConfig(level=config.log_level)

    mcp = build_server(config)
    mcp.run()


if __name__ == "__main__":
    main()
