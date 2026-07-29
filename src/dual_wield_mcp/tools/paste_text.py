import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.input import _paste_via_clipboard

logger = logging.getLogger(__name__)


def register_paste_text_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def paste_text(text: str) -> str:
        """Set the clipboard to text and paste it via ctrl+v, in one call.

        Combines clipboard_set followed by key_press("ctrl+v") into a single
        server-side call -- the same mechanism type_text now falls back to
        automatically for text over 100 characters, without needing two
        separate tool calls. Focus the target field first (e.g. via
        focus_window or a click), same as before either clipboard_set or
        key_press.

        Args:
            text: the string to place on the clipboard and paste.
        """
        if not text:
            raise ToolError("text must not be empty")

        logger.info("pasting text (%d chars)", len(text))
        _paste_via_clipboard(config, text)
        return f"pasted {len(text)} characters"
