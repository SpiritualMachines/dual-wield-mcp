import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.clipboard import _run_wl_copy
from dual_wield_mcp.tools.input import _resolve_key
from dual_wield_mcp.tools.input import _run as _ydotool_run

logger = logging.getLogger(__name__)


def register_paste_text_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def paste_text(text: str) -> str:
        """Set the clipboard to text and paste it via ctrl+v, in one call.

        Combines clipboard_set followed by key_press("ctrl+v") into a single
        server-side call -- the same pattern already recommended for long or
        special-character strings (URLs, search queries) over type_text's
        per-character simulated typing, without needing two separate tool
        calls. Focus the target field first (e.g. via focus_window or a
        click), same as before either clipboard_set or key_press.

        Args:
            text: the string to place on the clipboard and paste.
        """
        if not text:
            raise ToolError("text must not be empty")

        logger.info("pasting text (%d chars)", len(text))
        _run_wl_copy([config.wl_copy_path], text)

        codes = [_resolve_key(name) for name in ("ctrl", "v")]
        down = [f"{code}:1" for code in codes]
        up = [f"{code}:0" for code in reversed(codes)]
        _ydotool_run([config.ydotool_path, "key", *down, *up])

        return f"pasted {len(text)} characters"
