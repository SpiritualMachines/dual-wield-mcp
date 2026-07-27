import logging
import subprocess

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from dual_wield_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


def register_app_tools(mcp: FastMCP, config: ServerConfig) -> None:
    # config (unused) is accepted for consistency with the other register_*_tools
    # functions -- launch_app takes its target per-call, there's no fixed binary to
    # configure a path for.

    @mcp.tool()
    def launch_app(command: str, args: list[str] | None = None) -> str:
        """Launch a desktop application.

        Runs detached from this server process — it is not waited on, since GUI
        apps run indefinitely, and it survives this server restarting. The new
        window will not appear instantly; poll get_windows if you need to find
        it. To place it, use move_window/resize_window afterward rather than a
        position/size command-line flag: Wayland does not let a client set its
        own absolute position, so such flags are silently ignored by the
        compositor, but move_window/resize_window go through KWin's own
        scripting interface and take effect for real.

        Prefer this over a Bash command to launch anything: a Bash command
        needs a fresh permission grant for every never-before-seen invocation,
        even a literal, static one, whereas this tool is schema-validated
        (command/args are passed straight through as argv, never through a
        shell) and only needs allowlisting once, regardless of what command or
        args are passed afterward.

        Args:
            command: the binary to run, resolved via PATH (e.g. "brave") or an
                absolute path.
            args: command-line arguments, e.g. a URL to open.
        """
        if not command:
            raise ToolError("command must not be empty")

        cmd = [command, *(args or [])]
        logger.info("launching app: %s", cmd)
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise ToolError(f"{command} not found: {exc}") from exc

        return f"launched {command} (pid {process.pid})"
