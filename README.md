# dual-wield-mcp

MCP (Model Context Protocol) server exposing Linux desktop control to AI agents over Wayland, for Fedora Linux with KDE Plasma only. Built for dual-client compatibility with Claude Code and Hermes Agent.

## Status

v1.13.2 — Phases 1-12 and 15-17 complete; Phase 13 (session initialization and permission warm-up) mostly complete; Phase 18 (live LLM-driven navigation follow-ups) in progress. Phase 14 (Concurrent Input Detection) is exploratory, no version target. See [ROADMAP.md](ROADMAP.md).

**Tip:** call `focus_window` before `type_text`/`key_press` to target a specific window —
synthetic mouse clicks alone do not reliably transfer keyboard focus on KWin (see
ROADMAP.md Phase 2/3 for details).

## Requirements

- Fedora Linux with KDE Plasma (Wayland), Python 3.14+
- `spectacle` for screenshot capture (KDE's native screenshot tool — `grim`/`slurp`
  were tried first but depend on the `wlr-screencopy` protocol, which KWin does not
  implement)
- `ydotool` for input control, with `ydotoold` running as a user-level systemd service
  (requires `/dev/uinput` access — see uinput Permission Setup in ROADMAP.md)
- `kdotool` (KDE) or `wlrctl` (other wlroots compositors) for window management
- `wl-clipboard` (`wl-copy`/`wl-paste`) for `clipboard_set`/`clipboard_get`
- `tesseract` (OCR engine) for `find_text`
- Pillow and pytesseract (installed automatically as Python dependencies) for
  `inspect_region`'s image cropping and `find_text`'s OCR — no manual setup beyond the
  `tesseract` binary above

## Installation

Not published to PyPI yet — install from a local clone with [uv](https://docs.astral.sh/uv/)
as an isolated tool, so the `dual-wield-mcp` command lands on your `PATH` (at
`~/.local/bin`) where MCP clients can find it:

```bash
git clone <this-repo>
uv tool install ./dual-wield-mcp
```

For local development instead (editable install inside a project-local venv — note the
entry point then lives at `.venv/bin/dual-wield-mcp`, not on your global `PATH`):

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -e .
```

System dependencies (Fedora):

```bash
sudo dnf5 install kde-spectacle ydotool kdotool wlrctl wl-clipboard tesseract
```

`ydotoold` must run as your user, not root (the packaged system unit runs as root, which
leaves the daemon socket unusable by your session). Create
`~/.config/systemd/user/ydotoold.service` with:

```ini
[Unit]
Description=ydotool daemon (user session)

[Service]
Type=simple
Restart=on-failure
ExecStart=/usr/bin/ydotoold
KillMode=process

[Install]
WantedBy=default.target
```

Then enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service
```

## Usage

Run the server directly:

```bash
dual-wield-mcp
```

### Claude Code registration

Recommended — via the CLI (registers at `local` scope, personal to you and this project):

```bash
claude mcp add dual-wield -- dual-wield-mcp
```

Use `--scope project` instead to write the registration to `.mcp.json` in the repo root
and share it with your team via git.

Manual alternative — add this to `.mcp.json` (project scope) yourself:

```json
{
  "mcpServers": {
    "dual-wield": {
      "type": "stdio",
      "command": "dual-wield-mcp"
    }
  }
}
```

### Hermes Agent registration

```bash
hermes mcp add dual-wield --command dual-wield-mcp
```

`dual-wield` is just the label Hermes stores the server under; `--command` is the actual
binary to launch (verified against a real Hermes Agent v0.13.0 install — `hermes mcp add`
requires an explicit `--command` or `--url`, a bare server name alone is not enough).

### Recommended agent configuration

For best performance, specify in your agent's configuration (`CLAUDE.md`, `AGENT.md`, or
equivalent project instructions) that it should perform *all* desktop navigation and
interaction through this MCP server's tools — not a mix of manual shell commands, other
tools, and this server. Mixing approaches means some actions still go through ad hoc,
dynamically-constructed shell commands, which can trigger a permission prompt on every
single invocation regardless of any allowlist entry (Claude Code flags shell syntax it
cannot statically analyze, such as command substitution, every time). Each such prompt
interrupts the agent mid-task and requires clicking into the agent's own window to
respond, which can itself change focus on the desktop being automated. Routing
everything through this server's typed, schema-validated tools avoids that class of
prompt entirely once the tools are allowlisted by name.

For clients that support pre-approving tools by name (Claude Code's
`.claude/settings.json`/`settings.local.json`, via `permissions.allow`), pre-populate
it with every tool listed under Tools below, rather than letting each one hit its own
first-use approval prompt scattered across a session. Confirmed live: doing this
eliminates a fresh session's scattered-prompt problem entirely, with no server changes
needed. List each tool explicitly as `mcp__dual-wield__<tool_name>` (e.g.
`mcp__dual-wield__mouse_click`) — a `mcp__dual-wield__*` wildcard entry is also
accepted, but community reports (anthropics/claude-code issues #3107, #6010) say the
wildcard form alone isn't always honored, so keep the explicit per-tool list alongside
it rather than relying on the wildcard by itself.

### A note on the desktop session environment

MCP clients (including the reference Python SDK used by Claude Code) only pass a small,
curated allowlist of environment variables to the server subprocess by default — `HOME`,
`LOGNAME`, `PATH`, `SHELL`, `TERM`, `USER`. `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`,
and `XDG_RUNTIME_DIR` are *not* included, which breaks every tool here (`spectacle`,
`kdotool`, `ydotool` all need at least one of them). `dual-wield-mcp` fills in the
standard systemd-user-session defaults for these at startup if they're missing
(`/run/user/<uid>`, `unix:path=<runtime_dir>/bus`, `wayland-0`), so this works
out of the box for the common single-session desktop. If you run multiple Wayland
sessions or a non-standard setup, override them explicitly via the client's `env` config
for the server (e.g. an `"env": {"WAYLAND_DISPLAY": "wayland-1"}` block).

## Configuration

Environment variables (all optional):

| Variable                     | Default                                       |
|-------------------------------|-----------------------------------------------|
| `DUAL_WIELD_SCREENSHOT_DIR`   | `~/.local/share/dual-wield-mcp/screenshots`   |
| `DUAL_WIELD_SPECTACLE_PATH`   | `spectacle`                                   |
| `DUAL_WIELD_YDOTOOL_PATH`     | `ydotool`                                     |
| `DUAL_WIELD_KDOTOOL_PATH`     | `kdotool`                                     |
| `DUAL_WIELD_WLRCTL_PATH`      | `wlrctl`                                      |
| `DUAL_WIELD_KSCREEN_DOCTOR_PATH` | `kscreen-doctor`                           |
| `DUAL_WIELD_WL_COPY_PATH`     | `wl-copy`                                     |
| `DUAL_WIELD_WL_PASTE_PATH`    | `wl-paste`                                    |
| `DUAL_WIELD_TESSERACT_PATH`   | `tesseract`                                   |
| `DUAL_WIELD_WINDOW_BACKEND`   | `auto` (`auto`, `kde`, or `wlroots`)          |
| `DUAL_WIELD_LOG_LEVEL`        | `INFO`                                        |

## Tools

- `initialize()` — call this once, as the first action in a new session, before any task-driven tool use. Pre-warms `mouse_move`'s pointer calibration (the first real click of a fresh session can otherwise land off-target while that calibration is still converging) and returns a snapshot of session-start desktop state — display scale, detected window backend, and (KDE backend only) a fresh window listing — instead of rediscovering it reactively call by call.
- `screenshot(mode="full"|"region", output_path=None, include_image=True)` — captures the desktop via `spectacle` in background mode, optionally selecting a region first via an on-screen drag selection. Returns the saved file's absolute path as text, followed by the captured image. Pass `include_image=False` to return only the path when the screenshot is just input to `find_text`/`click_text` and won't be viewed directly — skips sending the image for vision processing.
- `inspect_region(path, x, y, width, height, output_path=None)` — crops a rectangular region out of an existing screenshot for close-up pixel inspection, without shelling out to `magick`/`identify`. Returns the cropped file's absolute path as text, followed by the cropped image.
- `mouse_move(x, y, space="physical")` — move the pointer to an absolute screen position. `space="logical"` accepts `get_windows`/`move_window`-style coordinates directly, converting via the display scale instead of requiring the caller to do it by hand.
- `mouse_click(button="left", x=None, y=None, space="physical", expected_window_class=None, double=False)` — click a mouse button (`left`, `right`, `middle`, `side`, `extra`, `forward`, `back`, `task`). Pass `x`/`y` (and optionally `space`, same meaning as `mouse_move`'s) to move the pointer there first and click in one call — required together, and removes the MCP round trip a separate `mouse_move` + `mouse_click` pair leaves open for the user's own live mouse movement to land in; omit both to click wherever the pointer already is. If `expected_window_class` is given, verifies the focused window's class (after any move, immediately before clicking) and raises `ToolError` on a mismatch instead of clicking a possibly stale target (KDE backend only). Pass `double=True` to double-click (two clicks within this one call, separated by a short server-side delay) — two separate `mouse_click` calls do not reliably register as a double-click, since the round trip between them is slower than the desktop's double-click timing threshold.
- `key_press(keys)` — press a key or `+`-joined combination (e.g. `"ctrl+shift+t"`).
- `type_text(text, expected_window_class=None)` — type a literal string. Text over 100 characters is pasted via the clipboard instead of typed — a single atomic paste, immune to the partial-type corruption a killed-on-timeout `ydotool type` can leave behind, but it overwrites the current clipboard contents. Text at or under 100 characters is still typed via `ydotool` with no clipboard side effect; if that call times out, the error explicitly warns that partial text may already be in the focused window rather than failing silently. If `expected_window_class` is given, verifies the focused window's class both before and after typing or pasting, raising `ToolError` on a mismatch — the post-check catches focus drift (e.g. the user alt-tabbing) mid-action (KDE backend only).
- `get_windows()` — list visible windows with id, title, class, pid, and position/size. KDE backend only (`wlrctl` has no window-listing command). Note: position/size are in KWin's logical (HiDPI-scaled) pixels, which can differ from the physical pixels used by `screenshot`/mouse tools.
- `get_active_window()` — metadata for the currently focused window, same fields as `get_windows`. KDE backend only. Use before `type_text`/`key_press` to confirm the window you think is focused actually is, instead of trusting a stale `get_windows`/`focus_window` result.
- `focus_window(window)` — activate (focus and raise) a window by id (KDE) or title substring (either backend). Use this before `type_text`/`key_press` to reliably target a specific window — see the Tip above.
- `wait_for_window(title=None, window_class=None, timeout=10.0)` — poll for a window matching a title substring and/or class substring, returning its metadata as soon as it appears instead of raising after a fixed sleep. Use this after `launch_app` instead of a manual `get_windows` polling loop. KDE backend only.
- `close_window(window)` — close a window by id or title substring. KDE backend only (`wlrctl` has no close action). Prefer this over a Bash `kill <pid>`, which needs a fresh permission grant for every never-before-seen pid.
- `move_window(window, x, y)` / `resize_window(window, width, height)` — move or resize a window by id or title substring, in KWin's logical pixels (same space as `get_windows`). KDE backend only. Goes through KWin's own scripting interface, so it works even where a launched application's own `--window-position`/`--window-size` flags are silently ignored by Wayland. Waits briefly before returning so a screenshot taken immediately after doesn't catch the window still animating into place.
- `launch_app(command, args=None)` — launch a desktop application via a direct `subprocess.Popen` inside the server, detached and not waited on. Prefer this over a Bash command to launch anything: a never-before-launched binary always needs a fresh Bash permission grant even as a literal command, while this tool only needs allowlisting once regardless of what's launched afterward. Position the new window with `move_window`/`resize_window` once it appears, rather than a launch-time position flag.
- `clipboard_set(text)` / `clipboard_get()` — set or read the Wayland clipboard via `wl-copy`/`wl-paste`. Prefer `paste_text` (below) over calling this plus `key_press("ctrl+v")` separately unless you need the clipboard set without pasting immediately.
- `paste_text(text)` — `clipboard_set` followed by `key_press("ctrl+v")` in one server-side call — the same mechanism `type_text` now falls back to automatically above 100 characters, without needing two separate tool calls. Focus the target field first, same as `type_text`/`key_press`.
- `find_text(path, query, case_sensitive=False, window=None)` — locate text in a screenshot via local OCR (tesseract), returning each matching line's text, bounding box, and center point in the same physical-pixel space `mouse_move`/`mouse_click` use. Use this to click a specific labeled button, link, or menu item without a manual screenshot -> `inspect_region` -> eyeball-the-pixel loop. Not infallible — treat a single high-confidence match as safe to click directly, and fall back to a visual check on multiple matches or low confidence. Pass `window` (a window id from `get_windows`, or a title substring) to scope OCR to just that window's region — the screenshot is cropped to the window's bounds before OCR runs, and returned coordinates are translated back to absolute screen space. Use this whenever the query text could plausibly appear elsewhere on the desktop too (most commonly the calling agent's own visible terminal), since without scoping, OCR can merge real text from the target window with unrelated text from a different window into one line, silently shifting the match off target rather than cleanly refusing. KDE backend only.
- `click_text(query, path=None, case_sensitive=False, button="left", min_confidence=40.0, expected_window_class=None, window=None)` — finds `query` via OCR and clicks it in one server-side call: captures a fresh screenshot if `path` is omitted, and only acts when there is exactly one match at or above `min_confidence`. No image is ever sent back for review on this path. Refuses (`ToolError`) on zero, multiple, or low-confidence matches instead of guessing — fall back to `find_text` plus a visual check in that case. `min_confidence` only ever gates the single-remaining-candidate case (multiple matches are always refused regardless of confidence); OCR confidence is a noisy signal, not a reliable correctness proxy in either direction, so raise it to be more conservative or lower it if a real match is being refused for scoring low. `window` has the same scoping semantics as `find_text`'s parameter.
- `read_screen_text(path=None, window=None)` — like `find_text` but with no query filter: returns every detected line of text and its position, sorted top-to-bottom then left-to-right. Captures a fresh screenshot if `path` is omitted. Use this to read a whole board, grid, or list in one call (e.g. every revealed number in a puzzle game, or every row of a file list) instead of several `find_text` calls or eyeballing `inspect_region` crops one at a time. `window` scopes the read to one window's region, same semantics as `find_text` — but note this is not automatically a strict improvement: cropping can occasionally cause tesseract to miss stylized/hyperlink text it would find with full-page context, so prefer scoping when disambiguating a click target and prefer a full, unscoped read when bulk-reading content matters more than excluding unrelated text.
