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


def _run_wl_copy(cmd: list[str], input_text: str) -> None:
    # wl-copy forks and keeps running in the background to serve future paste
    # requests (see wl-clipboard(1), "By default, wl-copy forks and serves data
    # requests in the background"); the backgrounded child inherits this
    # process's stdout/stderr pipe file descriptors and holds them open for as
    # long as it keeps running. subprocess.run()'s communicate() -- used by
    # _run() above -- waits for EOF on both pipes, which never arrives while
    # that background copy is alive, so every successful call would otherwise
    # block until the timeout even though the clipboard was already set.
    # Confirmed empirically: a successful wl-copy call left its process running
    # (ps showed it still alive, unrelated to the input length) while
    # subprocess.run() blocked for the full timeout regardless.
    #
    # Popen.wait() only waits for the immediate process's exit -- which happens
    # right after it forks -- and never touches the pipes, so it isn't affected.
    # On failure, wl-copy exits before ever forking, so its stdout/stderr close
    # normally and reading them afterward is safe (no backgrounded child left
    # holding them open).
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} not found: {exc}") from exc

    # A single write is safe here: clipboard text (paragraphs, URLs, search
    # queries) stays well under the OS pipe buffer size in practice, unlike a
    # generic large-payload pipe.
    proc.stdin.write(input_text)
    proc.stdin.close()

    try:
        returncode = proc.wait(timeout=_SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        raise ToolError(f"{cmd[0]} timed out after {_SUBPROCESS_TIMEOUT}s") from exc

    if returncode != 0:
        stderr = proc.stderr.read()
        raise ToolError(f"{cmd[0]} failed: {stderr.strip()}")


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
        _run_wl_copy([config.wl_copy_path], text)
        return f"set clipboard ({len(text)} chars)"

    @mcp.tool()
    def clipboard_get() -> str:
        """Read the current Wayland clipboard contents as text, via wl-paste."""
        logger.info("reading clipboard")
        return _run([config.wl_paste_path, "--no-newline"])
