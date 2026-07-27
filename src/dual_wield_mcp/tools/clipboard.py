import logging
import subprocess

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 10


def _run(cmd: list[str], input_text: str | None = None) -> str:
    # list-form argv (no shell=True) so clipboard content can never be interpreted
    # as shell syntax
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"{cmd[0]} timed out after {_SUBPROCESS_TIMEOUT}s") from exc

    if result.returncode != 0:
        raise ToolError(f"{cmd[0]} failed: {result.stderr.strip()}")
    return result.stdout


def register_clipboard_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def clipboard_set(text: str) -> str:
        """Set the Wayland clipboard to a literal text string, via wl-copy.

        Prefer clipboard_set followed by key_press("ctrl+v") over type_text
        for long or special-character strings (URLs, search queries): setting
        the clipboard and pasting is a single atomic operation, unlike
        type_text's per-character simulated typing.

        Args:
            text: the string to place on the clipboard.
        """
        if not text:
            raise ToolError("text must not be empty")
        logger.info("setting clipboard (%d chars)", len(text))
        _run([config.wl_copy_path], input_text=text)
        return f"set clipboard ({len(text)} chars)"

    @mcp.tool()
    def clipboard_get() -> str:
        """Read the current Wayland clipboard contents as text, via wl-paste."""
        logger.info("reading clipboard")
        return _run([config.wl_paste_path, "--no-newline"])
