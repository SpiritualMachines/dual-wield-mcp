# Desktop Navigation Benchmark

A standardized, repeatable exercise of the full dual-wield-mcp tool suite
against real applications on a real KDE Plasma Wayland desktop, so a change
to any tool (`launch_app`, `wait_for_window`, `read_screen_text`,
`find_text`, `click_text`, `mouse_move`/`mouse_click`, `key_press`,
`focus_window`, `close_window`, `get_windows`/`get_active_window`) can be
checked against a fixed baseline of realistic navigation tasks, instead of
relying on one-off live testing.

## Why this exists, and why it's different from `benchmarks/find_text/`

A live KMines session was used to validate `read_screen_text` and surfaced a
real gap: it returned zero lines for the game's revealed number grid. Digging
in (see CHANGELOG / ROADMAP for the root cause -- tesseract's default page
segmentation does not treat a small grid of isolated colored digits as a text
region, and even a tight crop merges adjacent digits across the thin cell
border into garbage like `"1/1/12"`) confirmed this is real, but narrow: it
is specific to dense, bordered digit/icon grids, not to what this tool is
actually for. Minesweeper was never the target use case -- **general desktop
navigation** is: menus, dialogs, file listings, buttons, settings panels.
This benchmark tests that instead.

It is deliberately **not** a synthetic, pixel-reproducible benchmark like
`find_text`'s. `find_text`'s benchmark isolates OCR accuracy against
deterministic rendered fixtures, on purpose, so it stays stable over time and
never touches a live desktop. That is the wrong shape for this benchmark:
the entire point here is whether the tools chain together correctly against
a *real* compositor, *real* window manager focus/geometry behavior, and
*real* application rendering -- exactly what a synthetic fixture cannot
exercise. The tradeoff is that this benchmark is not perfectly deterministic
(covered under Known Variability below); that is an accepted cost of testing
real integration rather than isolated OCR accuracy.

## Design

- **Calls the real code path.** `run_benchmark.py` builds the actual server
  (`build_server(ServerConfig.from_env())`) and drives it via
  `mcp.call_tool(...)` in-process -- the same tool functions a live MCP
  client calls, not a reimplementation. Real `spectacle`/`tesseract`/
  `ydotool`/`kdotool` subprocesses run underneath, same as a live session.
- **Two scenarios against stable, near-universal KDE apps** (both ship with
  Plasma, so this doesn't depend on anything exotic being installed):
  - `kwrite_menu_and_about` -- launch KWrite, read its menu bar in one
    `read_screen_text` call, open the Help menu via the `Alt+H` keyboard
    mnemonic, click "About KWrite" via `find_text`, bulk-read the About
    dialog's content, close it, close the main window.
  - `dolphin_file_listing_and_navigation` -- launch Dolphin pointed at a
    fixed synthetic directory (see Fixture below), bulk-read the file
    listing in one `read_screen_text` call, click into a named subfolder
    and confirm navigation via the window title, close the window.
- **Fixture directory, not real files.** `_setup_fixture_dir()` recreates
  `fixture_dir/` fresh on every run with a fixed, deterministic set of empty
  files (`alpha_report.txt`, `bravo_photo.png`, `charlie_notes.md`,
  `echo_archive.zip`, `delta_folder/`). This was a deliberate choice after
  KWrite's own "Recent Documents" welcome page turned out to surface real
  personal file paths and message content during scenario design -- this
  benchmark never reads or records real user files, and `fixture_dir/` is
  gitignored so it's never committed.
- **Objective pass/fail per step, not a visual eyeball.** Each step is a
  small async check returning `(ok, detail)`; a raised exception (a real
  `ToolError` from a tool call) is caught and recorded as a failed step
  rather than crashing the whole run, so one broken step doesn't prevent the
  other scenario from reporting.
- **Results appended, not overwritten.** Same pattern as `find_text`'s
  `RESULTS.md`: an append-only log of every run's per-step outcome and
  timing, so runs over time show whether changes make real navigation
  faster or more reliable.

## Running it

```bash
.venv/bin/python benchmarks/desktop_navigation/run_benchmark.py
```

Requires a running KDE Plasma Wayland session with `ydotoold` active (the
script checks and reports clearly if it's not) and `kwrite` + `dolphin`
installed. Exits non-zero if any step fails. **This takes over the mouse and
keyboard and opens real windows on the real desktop it's run from** -- do
not run it while doing anything else with the machine.

## Findings recorded so far

These came directly out of building and running this benchmark, and are
exactly the kind of thing it exists to catch on future runs. #2, #3, and #4
were fixed the same day they were found (v1.7.0); the rest are documented
behavior or open, accepted trade-offs.

1. **`read_screen_text` correctly groups a real menu bar as one line.** This
   is the *correct* behavior (it's genuinely one contiguous bar), but it
   means an individual menu item (e.g. "Help") is not independently
   `click_text`-able within that merged line -- there's no single word
   bounding box for just "Help" once tesseract groups the whole bar
   together. **Keyboard mnemonics (`Alt+<letter>`) are the reliable way to
   open an app's menu**, not `click_text` on the bar. Once a menu is *open*,
   each item is on its own row with real vertical separation and
   `find_text`/`click_text` work on it normally.

2. **Fixed (v1.7.0): a real, reproducible correctness gap, not just an
   ambiguity refusal.** In the baseline run, the About dialog's real "Close"
   button merged, via tesseract's line-grouping, with unrelated text from a
   different window that happened to sit close by on screen (`"X Close |
   Line result."` -- the second half was this session's own terminal). The
   merged bounding box's center point was pulled outside the dialog entirely.
   This is worse than the "N matches, refuse" ambiguity case: it produced
   exactly **one** match with a silently wrong coordinate, which `click_text`
   would have confidently clicked on if it had been the only candidate.
   Fixed by the `window` parameter described in finding #3 below -- cropping
   to the target window *before* running OCR means the unrelated terminal
   text is never seen by tesseract in the first place, so it can't merge
   with anything. Verified live: `find_text(query="Close", window=<About
   dialog id>)` now returns exactly the correct match at the real button's
   coordinates. This scenario's `close_about_dialog` step now passes.

3. **Fixed (v1.7.0): `find_text`, `read_screen_text`, and `click_text` gained
   a `window` parameter** (window id from `get_windows`, or a title
   substring). When given, the screenshot is cropped to that window's
   physical bounds *before* OCR runs, and returned coordinates are
   translated back to absolute screen space -- so a caller gets the
   convenience of a crop (no unrelated text from elsewhere on the desktop
   can match or merge in) without the previous problem of crop-relative
   coordinates being wrong when handed to `mouse_move`/`mouse_click`
   (`inspect_region` output was never safe to feed to `click_text` for this
   reason, and still isn't -- `window` is the correct tool for "scope to one
   window," not a workaround crop). KDE backend only (no per-window geometry
   query on wlrctl).

4. **Fixed (v1.7.0): `mouse_click` gained a `double: bool` parameter.** Two
   sequential `mouse_click` calls do not register as a double-click -- the
   inter-call latency (tool round trip + subprocess spawn) exceeds the
   desktop's double-click timing threshold, confirmed live (two calls landed
   as select-then-reselect, not open). `double=True` issues both clicks
   within one call with a short server-side sleep in between, comfortably
   under typical thresholds. `navigate_into_folder` uses this directly now.
   The `focus_window` + `key_press("enter")` pattern (documented in the
   `mouse_click` docstring) remains the recommended default when the target
   has a keyboard-activation equivalent, since it doesn't depend on desktop
   double-click timing configuration at all -- `double=True` is for when it
   doesn't.

5. **Launched apps' window classes don't always match the launch command.**
   `kwrite` launches as `org.kde.kwrite`; `dolphin` happened to match as
   `org.kde.dolphin` on the first try. Guessing wrong wastes a full
   `wait_for_window` timeout. Worth a quick `get_windows` check when a new
   app's class is unknown, rather than assuming the binary name.

6. **Image files can occasionally render with a garbled filename in
   Dolphin's listing.** `bravo_photo.png` OCR'd as unrelated garbage in one
   run, while the `.txt`/`.md`/`.zip` fixture files read correctly --
   plausibly thumbnail-preview rendering interfering with the filename text
   for image types specifically. Not reproduced on every run (a later run
   read all five names correctly), so likely timing-dependent on thumbnail
   generation. `bulk_read_file_listing` tolerates exactly one such miss out
   of the fixture set; a regression here would need two or more misses to
   fail.

7. **Window-scoped OCR is not a strict superset of full-page OCR --
   cropping can lose content tesseract would otherwise find.** Discovered
   while validating the finding #3 fix: the About dialog's two
   hyperlink-styled lines ("License: GNU Lesser General Public License
   Version 2" and the `kate-editor.org` URL) appear in a full-screenshot
   `read_screen_text` call, but are absent from a `window`-scoped read of
   the *exact same dialog, from the same screenshot file*. Tesseract's page
   segmentation evidently makes different decisions about stylized/link text
   depending on how much surrounding page context it has to work with, not
   just the local pixels. Net effect: `window` scoping is the right tool for
   disambiguating a *click target* (finding #3), where an extra unrelated
   match is the failure mode to avoid -- it is not automatically the right
   choice for *bulk reading a window's content*, where losing real lines is
   the worse failure mode. `read_about_dialog_content` reads the full
   screenshot deliberately, not window-scoped, for exactly this reason. No
   code fix attempted here; noted as an open, accepted trade-off rather than
   a bug, since "read everything, then filter" and "crop, then read" are
   both reasonable strategies depending on which failure mode matters more
   for a given call.

## Known variability

Unlike `find_text`'s synthetic benchmark, this one is not immune to what
else is on screen: finding #2 is a direct example -- a real result depended
on what window happened to be nearby, and finding #6 didn't reproduce on
every run. Placement (`WINDOW_X`, `WINDOW_Y`, `WINDOW_W`, `WINDOW_H` in
`run_benchmark.py`) is fixed, but whatever else is on the desktop when this
runs is not controlled by the script. Whoever runs this live should check
`get_windows` first and be mindful of what's on screen, same as any other
live tool use -- the script does not attempt to hide or rearrange unrelated
windows.
