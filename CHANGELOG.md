# Changelog

## [1.13.3] - 2026-07-29

### Changed

- `click_text` no longer refuses a single, unambiguous match for scoring
  below a confidence threshold. The `min_confidence` parameter and
  `_DEFAULT_MIN_CONFIDENCE` constant are removed entirely, discussed and
  decided directly with the user rather than retuning the default a third
  time (it had already moved 60 -> 40 in [1.10.0] and was still refusing
  real matches at 37.3%). The ambiguity check (multiple matches always
  refuse) was already the real safety net; confidence has been shown live
  not to reliably track correctness in either direction (a real match as
  low as 37.3%; a genuine misread at 87%, see [1.10.0]/[1.4.0]). A single
  match now always acts and still reports its confidence score in the
  result text. Completes Phase 18; see ROADMAP.md.

## [1.13.2] - 2026-07-29

### Added

- `type_text` now auto-falls-back to pasting via the clipboard for text over
  100 characters, instead of simulating keystrokes -- a single atomic paste
  rather than one `ydotool` call per character, and immune to the
  partial-type corruption a killed-on-timeout `ydotool type` can leave
  behind. Overwrites the clipboard as a side effect for long text,
  documented in `type_text`'s docstring. New shared `_paste_via_clipboard`
  helper in `input.py` backs both this fallback and the standalone
  `paste_text` tool, which now calls it instead of duplicating the
  clipboard-set-then-paste steps. Completes Phase 16a's last open item; see
  ROADMAP.md.

### Removed

- The length-aware timeout scaling added in [1.9.0] (`_TYPE_MS_PER_CHAR`,
  `_TYPE_TIMEOUT_MARGIN_SECONDS`) is gone. With the new 100-character paste
  threshold, `type_text`'s typing path never handles text long enough for
  that scaling to matter (worst case ~4.5s at `ydotool`'s documented
  ~40ms/char, well under the flat 10s timeout) -- it had become unreachable
  dead code, so it was removed rather than left in place.

## [1.13.1] - 2026-07-29

### Fixed

- `wait_for_window`'s `window_class` match was exact (`==`), while its
  `title` match was already substring. KDE apps almost always report a
  class like `org.kde.kwrite`, never the bare binary name, so
  `wait_for_window(window_class="kwrite")` -- the natural guess right after
  `launch_app("kwrite")` -- was close to always wrong. `class_ok` is now a
  case-insensitive substring/contains check, same shape as `title_ok`.
  Surfaced live twice: Phase 12's finding #5 and again during a live
  agent-driven navigation test (Phase 18). See ROADMAP.md Phase 18.

## [1.13.0] - 2026-07-28

Phase 13 (Session Initialization & Permission Warm-Up) mostly complete --
the original permission-prompt problem this phase was named for turned out
to have a simpler client-config fix (see [1.1.1]/README's allowlist
guidance), but a real, live-observed gap remained: the very first click of
a fresh session missed its target twice in separate test runs.

### Added

- New `initialize()` tool. Call it once, as the first action in a new
  session, before any task-driven tool use (the server's `instructions` now
  say so explicitly). Pre-warms `mouse_move`'s closed-loop pointer
  calibration with two real moves (display center, then an off-center
  point) so it isn't still converging on the first real, task-driven click
  -- the observed cause of the first-click-miss. Also returns a
  consolidated snapshot of session-start desktop state (display scale,
  detected window backend, and a fresh window listing on the KDE backend)
  instead of the agent rediscovering it reactively call by call. New
  `_get_display_size` helper in `input.py`, reading the same
  `kscreen-doctor -j -o` payload `_get_display_scale` already does.

### Fixed

- Pinned `mcp[cli]` to `>=1.28.1,<2.0.0`. The upstream `mcp` SDK published a
  breaking v2.0.0 release that removes `mcp.server.fastmcp` entirely; the
  previously unbounded `>=1.28.1` constraint let a routine reinstall pull
  it in and silently break the installed server (`ModuleNotFoundError:
  No module named 'mcp.server.fastmcp'`), surfacing as a live MCP
  reconnect failure. `pyproject.toml` and `requirements.txt` now both cap
  it below 2.0.0, the actual tested range.

### Known limitations

- The pre-warm's effectiveness was not independently re-verified live
  (re-running against a fresh server process to compare first-click
  accuracy with and without it) -- covered by unit tests asserting the
  exact calibration targets computed instead. See ROADMAP.md Phase 13 for
  the reasoning.
- One originally-scoped item remains: once Phase 14 (Concurrent Input
  Detection) exists, have `initialize()` ask the user whether to arm it for
  the session. Not yet started.

## [1.12.0] - 2026-07-28

Phase 17 (Live-Feedback Follow-ups) complete -- the fourth and final item
from the Hermes Agent feedback review.

### Fixed

- `move_window`/`resize_window` sometimes left the window still animating
  into place when the very next tool call was a `screenshot`, catching a
  transitional frame. Both now wait `_WINDOW_SETTLE_DELAY_SECONDS` (0.25s)
  after issuing the move/resize before returning. Chosen as the midpoint of
  the 200-300ms range suggested from the live observation; KWin's actual
  animation duration for a scripted (non-drag) geometry change wasn't
  isolated and measured directly, so this is a reasonable estimate rather
  than a verified exact figure.

## [1.11.0] - 2026-07-28

Phase 17 (Live-Feedback Follow-ups) advanced with a third item -- the
window-scoped OCR crop-edge miss reported in the same Hermes Agent feedback
review as the previous release. One item (a move/resize settle delay)
remains proposed.

### Fixed

- Window-scoped OCR (`find_text`/`read_screen_text`/`click_text`'s `window`
  parameter) occasionally missed text sitting right at the crop edge,
  observed live on a `clamtk` window. The crop now pads the window's
  reported bounds by 8 physical pixels on each side before clamping to the
  screenshot's own edges (`_WINDOW_CROP_PADDING` in `ocr.py`), absorbing
  rounding slop between the window's reported geometry and its actually
  painted content without growing large enough to plausibly pull in a
  neighboring window and reintroduce the cross-window text merging window
  scoping exists to prevent (see the [1.7.0] entry below).

## [1.10.0] - 2026-07-28

Phase 17 (Live-Feedback Follow-ups) partially complete -- the two
highest-value items from a live "ask the agent for feedback" review with
Hermes Agent, addressed first per the user's own prioritization. The
remaining two items (window-scope crop padding, a move/resize settle delay)
stay proposed.

### Added

- New `paste_text(text)` tool: `clipboard_set` followed by
  `key_press("ctrl+v")` in one server-side call. The two-call version was
  already the documented recommended pattern for long or special-character
  strings over `type_text`'s simulated typing; this collapses it into a
  single round trip, the same rationale as `mouse_click`'s `x`/`y`/`space`
  parameters and `click_text`. Covered by 3 new tests in
  `tests/test_paste_text.py`.

### Changed

- `click_text`'s default `min_confidence` lowered from 60.0 to 40.0. A live
  test found a real, unambiguous, correct match ("Select a directory")
  scored only 48% confidence and was wrongly refused. On closer reading,
  `min_confidence` only ever gates the single-remaining-candidate case --
  multiple substring matches are always refused as ambiguous regardless of
  confidence -- and `benchmarks/find_text/README.md` already documents a
  genuine misread scoring 87%, confirming OCR confidence isn't a reliable
  correctness signal in either direction. 40.0 sits below the real 48%
  false-refusal and above the 30.0 already used as a "should refuse"
  fixture in `tests/test_click_text.py`. Covered by a new regression test.

## [1.9.0] - 2026-07-28

Phase 16 (Long-Text Input Timeout & Partial-Type Corruption) complete --
fixes two distinct bugs surfaced by a live Hermes Agent + local-model
end-to-end test, both sharing the same flat `_SUBPROCESS_TIMEOUT = 10`
symptom but with different root causes.

### Fixed

- `type_text` now scales its timeout with the string's length instead of a
  flat 10s ceiling. `ydotool type` simulates real per-character keystrokes,
  so a long paragraph legitimately took longer than 10s to type, and
  Python's `subprocess.run(..., timeout=...)` SIGKILLs the child on
  timeout -- killing `ydotool type` mid-keystream and leaving corrupted,
  partially-typed text in the target window, confirmed live via a garbled
  file diff. The timeout is now `max(10s, 3s + 45ms * len(text))`. If a
  timeout still occurs, the error now explicitly warns that partial text
  may already be in the focused window, instead of a generic timeout
  message.
- `clipboard_set` no longer hangs for the full timeout on every call.
  Root-caused precisely: `wl-copy` forks and keeps running in the
  background to serve future paste requests (documented in
  `wl-clipboard(1)`), and the backgrounded process inherits and holds open
  the stdout/stderr pipe file descriptors `subprocess.run()` created to
  capture output. `communicate()` waits for EOF on both pipes, which never
  arrives while the background copy is alive -- so every successful
  `clipboard_set` call was blocking for the full 10s even though the
  clipboard had already been set correctly within milliseconds. Confirmed
  empirically (a successful call left `wl-copy` running indefinitely,
  independent of input length). Fixed by switching to `Popen` +
  `wait()` (which only waits for the immediate process's exit, not pipe
  EOF) instead of `run()`/`communicate()`.

## [1.8.0] - 2026-07-27

Phase 15 (Move-and-Click Round-Trip Reduction) complete -- closes the one
remaining gap `click_text` didn't already cover: clicking at an explicit
coordinate (e.g. read off an `inspect_region` crop) still needed a separate
`mouse_move` then `mouse_click` call, leaving a full MCP round trip open for
the user's own live mouse movement to land in between, on a machine where
the user routinely multitasks during a session.

### Added

- `mouse_click` gained optional `x`, `y`, and `space` parameters, mirroring
  `mouse_move`'s own coordinate contract. When `x`/`y` are given (both
  required together), the pointer moves there first via the same
  `_move_mouse_absolute` closed-loop correction `mouse_move` uses, then
  clicks -- all within the one call, removing the MCP round trip between a
  separate move and click. Omitting both keeps existing behavior: click
  wherever the pointer already is. `expected_window_class`, when given, is
  still checked once immediately before the click byte is sent (i.e. after
  any move). Covered by 7 new tests in `tests/test_input.py`.

### Known limitations

- Does not eliminate the exposure window entirely: `mouse_move`'s
  closed-loop correction can still take a few real iterations (subprocess
  spawn + readback) to converge before the click fires. Zero exposure is
  Phase 14's (deferred) territory -- detecting genuine human input at the
  device level and disengaging -- not this change's.

## [1.7.0] - 2026-07-27

Follows directly from `benchmarks/desktop_navigation/`, built the same day to
test the tool suite against real desktop-navigation tasks rather than the
KMines-style content `read_screen_text` was never meant for. That benchmark
immediately surfaced a real correctness gap and a real usability gap; both
are fixed here.

### Added

- `find_text`, `read_screen_text`, and `click_text` gained a `window`
  parameter (a window id from `get_windows`, or a title substring). When
  given, OCR runs only against that window's cropped region instead of the
  whole screenshot, with matched coordinates translated back to absolute
  physical-pixel screen space. Fixes a real correctness gap found live: an
  About dialog's genuine "Close" button merged, via the existing
  gap-splitting line-grouping logic, with unrelated text from a different
  window sitting nearby on screen (the calling agent's own visible
  terminal), silently shifting the match's center point outside the dialog
  entirely -- worse than an ambiguity refusal, since it was exactly one
  match and would have been clicked confidently. Implemented via a new
  `_ocr_lines_in_window`/`_find_text_in_window` pair in `tools/ocr.py` and a
  new sync `_kde_resolve_window_geometry` helper in `tools/window.py` (built
  on a `_parse_kdotool_metadata` extraction shared with the existing async
  metadata lookup, so the two can't drift apart). KDE backend only. Covered
  by 9 new tests across `tests/test_window.py`/`tests/test_ocr.py`, plus 2 in
  `tests/test_click_text.py`.
- `mouse_click` gained a `double: bool = False` parameter. Two sequential
  `mouse_click` calls do not reliably register as a double-click -- the
  round trip between them exceeds the desktop's double-click timing
  threshold, confirmed live (two calls landed as select-then-reselect, not
  an open action). `double=True` issues both clicks within the one call,
  separated by a short server-side sleep instead of an MCP round trip.
  Covered by 3 new tests in `tests/test_input.py`.

### Changed

- `benchmarks/desktop_navigation/run_benchmark.py` now uses `window` scoping
  for both click-target steps and `double=True` for folder navigation,
  replacing the manual bounds-filtering and click+focus+enter workarounds
  those steps needed before this release. Both scenarios now pass fully; see
  `benchmarks/desktop_navigation/README.md` for the full findings list,
  including one new trade-off discovered while validating the fix (window
  scoping can cause tesseract to miss stylized/hyperlink text it would
  otherwise find with full-page context -- not a bug, a documented,
  accepted trade-off, since bulk-reading and click-targeting want opposite
  failure modes).

## [1.6.0] - 2026-07-26

Follows a live KMines test: reading a revealed number grid was done by
visually eyeballing several `inspect_region` crops cell by cell instead of
using OCR, which was slower and more error-prone than it needed to be.

### Added

- `read_screen_text(path=None)` — new tool in `tools/ocr.py`. Like
  `find_text` but with no query filter: returns every detected line of text
  and its position in one call, sorted top-to-bottom then left-to-right,
  instead of requiring one `find_text` call per possible value or manual
  visual parsing of crops. Captures a fresh full-desktop screenshot if `path`
  is omitted, reusing `screenshot.py`'s `_capture_screenshot`. Shares OCR/
  grouping logic with `find_text` via a new `_ocr_lines_from_image` helper
  (extracted from `_find_text_in_image`, which now just adds the substring
  filter and confidence sort on top) so both tools run the same underlying
  code path. Covered by 6 new tests in `tests/test_ocr.py`.

## [1.5.0] - 2026-07-26

Cuts round trips and vision-processing cost out of the "click a labeled UI
element" workflow, following up directly on the find_text work above. Most
of `find_text`'s remaining round trips were workflow shape (screenshot ->
find_text -> mouse_move -> mouse_click, sometimes plus an `inspect_region`
fallback), not OCR speed — `find_text` itself was already local-only and
never sent image bytes anywhere.

### Added

- `click_text(query, path=None, case_sensitive=False, button="left",
  min_confidence=60.0, expected_window_class=None)` — new `tools/click_text.py`
  module. Combines screenshot + find_text + mouse_move + mouse_click into one
  server-side call: captures a fresh screenshot if `path` is omitted, and
  only moves/clicks when there is exactly one match at or above
  `min_confidence`. No image is sent to the calling agent on this path, and
  there is no gap between locating a target and acting on it for the desktop
  to change in. Refuses with `ToolError` (listing what was found) on zero,
  multiple, or low-confidence matches rather than guessing — the caller falls
  back to `find_text` plus a visual check only in that genuinely ambiguous
  case. `tools/ocr.py`'s `_find_text_in_image` and `tools/screenshot.py`'s
  new `_capture_screenshot` helper are reused directly, so this measures and
  runs the exact same code path as the standalone tools, not a
  reimplementation. Covered by 10 new tests in `tests/test_click_text.py`.
- `screenshot` gained an `include_image` parameter (default `True`). Passing
  `False` returns only the saved path as text, skipping the image content
  entirely — for callers (like `click_text`, and any manual
  screenshot -> find_text sequence) that only need the path as OCR input and
  were never going to view the picture, avoiding vision-processing cost on
  an image nothing looks at. Covered by a new test in `tests/test_screenshot.py`.

## [1.4.1] - 2026-07-26

Fixes a `find_text` accuracy bug found immediately during live use (the ClamTk
test in the same session as v1.4.0's release): icon-grid labels sharing the
same y-coordinate (e.g. "Settings Whitelist Network Scheduler") were merged
into a single OCR line by tesseract's `line_num`, making the returned center
coordinate useless for any one label and forcing a manual `inspect_region`
visual fallback almost every time — largely defeating the point of the tool.

### Fixed

- `_group_words_into_lines` now also splits a tesseract line into separate
  results wherever the horizontal gap between adjacent words exceeds 2.5x
  their height, distinguishing real prose (small inter-word gaps) from
  unrelated UI elements that only share a `line_num` because they sit at the
  same y-coordinate. Existing multi-word-phrase matching (e.g. "Engine
  Driver") is unaffected, since normal word spacing stays well under the
  threshold. Covered by a new test in `tests/test_ocr.py` using the exact
  icon-grid-label shape that failed live.

### Added

- `benchmarks/find_text/` — a standardized, reproducible accuracy/latency
  benchmark for `find_text`, so future changes to its OCR grouping logic can
  be checked against a fixed baseline instead of relying on one-off live
  testing (which surfaced the bug above but isn't a repeatable test surface).
  Synthetic fixtures generated deterministically via PIL (not captured
  screenshots, so results are reproducible across machines and no personal
  screen content is committed), scored against ground truth read directly
  from PIL's own `textbbox` at generation time. Calls the real
  `_find_text_in_image` code path (newly extracted from the `find_text` tool
  body for this purpose) rather than a reimplementation. Baseline run: 7/8
  scored cases passing, 1 documented known limitation, 1 newly-discovered
  real gap (small-text OCR misreads). See `benchmarks/find_text/README.md`.

## [1.4.0] - 2026-07-26

Phase 9 (Navigation Efficiency Tools) complete — reduces the number of round trips
and manual coordinate math a live workflow needs, rather than fixing a permission
or reliability failure like Phases 6/8.

### Added

- `wait_for_window(title=None, window_class=None, timeout=10.0)` — polls for a
  window matching a title substring and/or class, returning its metadata as soon
  as it appears. Replaces a manual `get_windows` polling loop or a fixed sleep
  after `launch_app`. KDE backend only.
- `clipboard_set(text)` / `clipboard_get()` — set or read the Wayland clipboard via
  `wl-copy`/`wl-paste`. New `tools/clipboard.py` module. `clipboard_set` followed
  by `key_press("ctrl+v")` is a single atomic operation, preferred over `type_text`
  for long or special-character strings (URLs, search queries).
- `mouse_move` gained a `space="physical"|"logical"` parameter. `space="logical"`
  accepts `get_windows`/`move_window`-style coordinates directly, doing the
  physical = logical * scale conversion internally instead of requiring the
  caller to do it by hand every time.
- `find_text(path, query, case_sensitive=False)` — locates text in a screenshot
  via local OCR (`tesseract`, wrapped by the new `pytesseract` dependency), and
  returns each matching line's bounding box and center point in the same
  physical-pixel space `mouse_move`/`mouse_click` use. New `tools/ocr.py` module.
  Lets an agent click a specific labeled button, link, or menu item directly
  instead of a manual screenshot -> `inspect_region` -> eyeball-the-pixel loop.

## [1.3.0] - 2026-07-25

Phase 8 (App Lifecycle & Window Placement) complete — moves the last Bash calls a
live workflow needed (launching an app, closing/positioning its window) into the
server as typed tools. Directly prompted by a live-testing failure: launching Brave
with `--window-position`/`--window-size` silently did nothing (Wayland does not let
a client set its own absolute position), and closing it via a Bash `kill <pid>`
triggered a permission prompt because every literal pid is a never-before-seen
command — and the "proactive fix" of editing `.claude/settings.local.json` to
pre-allowlist the next command *itself* triggered a second prompt, since modifying
the harness's own settings file needs the same approval every time in a fresh
session. That finding rules out "edit the allowlist first" as a general strategy;
the only prompt-immune mechanism is an MCP tool allowlisted by name once.

### Added

- `launch_app(command, args=None)` — launches a desktop application via
  `subprocess.Popen` inside the server process, detached and not waited on. New
  `tools/app.py` module.
- `close_window(window)` — closes a window by id or title substring, via `kdotool
  windowclose`.
- `move_window(window, x, y)` / `resize_window(window, width, height)` — move or
  resize a window by id or title substring, via `kdotool windowmove`/`windowsize`,
  which goes through KWin's own scripting interface and takes effect even where a
  launched application's own position/size flags are silently ignored.
- All three window tools are KDE-only (`wlrctl` has no close/move/resize actions)
  and share a new `_kde_resolve_window_ref` helper extracted from `focus_window`'s
  existing id-or-title-search logic.

## [1.2.0] - 2026-07-25

Phase 6 (Agent-Facing Robustness) complete — moves recurring agent-side Bash
workarounds and stale-window assumptions into the server itself as typed tools,
following two live-testing incidents: an agent acting on a stale window assumption
after a multi-step gap, and routine pixel-inspection Bash commands repeatedly
hitting Claude Code's "shell syntax cannot be statically analyzed" permission
prompt with no allowlist fix available.

### Added

- `inspect_region(path, x, y, width, height, output_path=None)` — crops a
  rectangular region out of an existing screenshot for close-up pixel inspection,
  replacing ad hoc `magick`/`identify` shell-outs. Uses Pillow (new dependency,
  pure-Python, no external binary). Validates dimensions, coordinates, file
  existence/readability, and that the region fits the source image's bounds.
- `screenshot` now returns the saved file's absolute path as text alongside the
  image (`[str(dest), Image(...)]`), instead of only inline image bytes, removing
  the need to rediscover "the most recent screenshot" via shell globbing.
- `get_active_window()` — metadata for the currently focused window (same fields
  as `get_windows`), via `kdotool getactivewindow`. KDE backend only.
- `mouse_click` and `type_text` gained an opt-in `expected_window_class`
  parameter: verifies the focused window's class before acting (and, for
  `type_text`, again afterward) and raises `ToolError` on a mismatch instead of
  acting on a possibly stale target. `mouse_click` checks only before acting,
  since a click can legitimately change focus itself; `type_text` checks both
  sides, since typing should not normally change focus, so a post-check can catch
  the user switching windows mid-action. Backend is detected lazily, only when
  the parameter is used, so setups with no window backend installed are
  unaffected. KDE backend only.

### Dependencies

- Added Pillow (`pillow>=12.3.0`) for `inspect_region`'s image cropping.

## [1.1.1] - 2026-07-25

### Fixed

- The server gave an agent no way to learn, without trial and error, that
  `get_windows` reports position/size in KWin's logical (HiDPI-scaled) pixels while
  `screenshot`/`mouse_move`/`mouse_click` operate in physical pixels. `FastMCP` was
  instantiated with no `instructions`, and no tool docstring mentioned pixel space.
  Found live: after a session restart, an agent with no prior context on this codebase
  burned many exploratory screenshot-crop calls rediscovering the conversion instead of
  being told upfront. Fixed by adding `instructions` to the `FastMCP(...)` server
  (`server.py::_INSTRUCTIONS`) documenting the two pixel spaces, the conversion, and the
  recommended workflow, and expanding the `get_windows`/`mouse_move`/`screenshot`
  docstrings to state their pixel space directly.

## [1.1.0] - 2026-07-25

Phase 5 (Optimization & Refinement) complete — reduces subprocess overhead found
during live use, no tool behavior or public API changes.

### Added

- Display scale (`kscreen-doctor -j -o`) is now cached after the first lookup instead
  of being re-queried on every `mouse_move` call (`input.py::_display_scale_cache`)
- The calibrated move ratio learned by `mouse_move`'s closed-loop correction now
  persists across calls instead of resetting to the empirical `2.33` guess each time
  (`input.py::_move_ratio_cache`) — later calls typically converge in fewer iterations
  once a ratio has been learned
- Window-backend detection (`_detect_backend`) now runs once at server startup
  (inside `register_window_tools`) instead of on every `get_windows`/`focus_window`
  call
- `get_windows` now fetches per-window `kdotool` metadata concurrently via
  `asyncio.gather` instead of one sequential subprocess spawn per window
  (`_run_async`, `_kde_get_window_metadata`)

### Investigated

- Whether `kdotool`/`ydotool` could batch compound actions (e.g. move + click) into
  a single subprocess call. Not possible: `ydotool` accepts exactly one top-level
  command per invocation with no chaining syntax; `kdotool` supports chaining but has
  no mouse move/click primitives at all (window management only). Not pursued
  further.

### Measured

- Re-measured `mouse_move` subprocess overhead against the real desktop: 15 calls to
  varied targets took 112 subprocess spawns before this work (7.5/call) vs. 82 after
  (5.5/call) — a 27% reduction — and a 1.33x wall-clock speedup (0.944s -> 0.709s for
  the batch). Spawn count is the more reliable metric; per-call wall time is noisier.

## [1.0.1] - 2026-07-25

### Fixed

- **`mouse_move` never actually moved the pointer to the requested position.**
  `ydotool mousemove --absolute -x/-y` (and the documented positional-argument form) is a
  no-op against KWin on this compositor — the cursor stayed pinned near the origin
  regardless of the target coordinates. This had been broken since 0.2.0: every prior
  test and live use only checked exit codes or side effects, never the actual resulting
  cursor position, so it went undetected through Phases 2-4. Found via direct pixel-level
  inspection of cursor position in screenshots during live testing. Root cause: absolute
  positioning does not work at all against this compositor, and even relative movement is
  skewed by KDE's non-linear pointer-acceleration curve (observed ~2.33x for a single
  large synthetic jump, and not constant). Fixed by replacing the single-shot absolute
  move with closed-loop correction: `mouse_move` now issues a relative move, reads back
  the true cursor position via `kdotool getmouselocation` (converted from KWin's
  logical/HiDPI pixels to the physical pixels used elsewhere via the scale factor from
  `kscreen-doctor`), and repeats up to 6 times until within 3px of the target, refining
  its per-axis move ratio from the observed result each iteration. Verified via
  pixel-level screenshot inspection and successful real-world use (clicking precise,
  previously-unreachable UI elements in a live app).

### Known limitations

- The closed-loop correction adds real subprocess overhead — up to ~19 spawns per
  `mouse_move` call in the worst case (1 `kscreen-doctor` + up to 6 iterations of 2
  `kdotool getmouselocation` + 1 `ydotool mousemove`). Tracked as Phase 5 optimization
  work in ROADMAP.md.
- `tests/test_input.py`'s `mouse_move` tests asserted the old, broken `--absolute -x/-y`
  command shape. Rewritten to exercise the real closed-loop correction against a fake
  cursor/display simulation instead of asserting a literal command list.

## [1.0.0] - 2026-07-25

First feature-complete release — all four roadmap phases done.

### Added

- Packaging verified: built a real wheel (`uv build`) and installed it with
  `uv tool install` into a clean environment, confirming the `dual-wield-mcp` console
  entry point works outside the dev venv
- Claude Code registration documented and corrected (see Fixed below)
- Hermes Agent registration documented per CLAUDE.md (`hermes mcp add`) — not
  independently verified, Hermes Agent was not available on the dev machine

### Fixed

- **Backend auto-detection worked in every prior test but silently failed on every real
  MCP client launch.** Root cause: MCP clients (including the reference Python SDK used
  by Claude Code) only pass a curated safe allowlist of environment variables to the
  server subprocess by default (`HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, `USER`).
  `XDG_CURRENT_DESKTOP` — which the Phase 3 backend detection depended on — is not in
  that allowlist, so it was always empty on a real launch, misdetecting `kde` as
  `wlroots`. All prior testing used in-process calls or direct subprocess invocation
  from a shell, both of which share the full parent environment and never exercised this
  path. Fixed by detecting on binary presence alone (`kdotool` preferred, `wlrctl`
  fallback) instead of the desktop-session env var.
- **Same root cause, worse impact:** `kdotool` (needs `DBUS_SESSION_BUS_ADDRESS`) and
  `spectacle` (needs `WAYLAND_DISPLAY`) both fail outright without those variables,
  which are equally absent from the MCP client's default subprocess environment. Fixed
  by having the server fill in the standard systemd-user-session defaults for
  `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and `WAYLAND_DISPLAY` at startup if
  they're missing (`server.py::_ensure_session_environment`). Documented in README as an
  override point for non-standard setups (multiple Wayland sessions, etc).
- Corrected the Claude Code registration instructions: `.claude/settings.json` with an
  `mcpServers` key (the original plan) is wrong. The actual mechanism is `claude mcp add`
  (recommended) or a `.mcp.json` file with a required `"type": "stdio"` field.

### Known limitations

- `get_windows` is KDE-only (see 0.3.0 below)
- `get_windows` geometry uses KWin's logical/HiDPI-scaled pixels, which differ from the
  physical pixels used by `screenshot`/mouse tools (this machine: 1.25x scale factor)
- `wlrctl` backend paths (Phase 3) are implemented against documented CLI/man page
  behavior but were never tested against a real wlroots compositor — only KDE Plasma was
  available on the dev machine

## [0.3.0] - 2026-07-25

### Added

- `get_windows`, `focus_window` MCP tools with auto-detected backend: `kdotool` on KDE
  Plasma, `wlrctl` fallback on other wlroots compositors (untested — no wlroots
  compositor available on the dev machine)
- Backend auto-detection via `XDG_CURRENT_DESKTOP` + binary presence, overridable with
  `DUAL_WIELD_WINDOW_BACKEND`

### Fixed

- Phase 2's known limitation (synthetic mouse clicks not transferring keyboard focus) is
  resolved by calling `focus_window` before `type_text`/`key_press` — confirmed via live
  test, see ROADMAP.md Phase 3

### Known limitations

- `get_windows` is KDE-only: `wlrctl`'s foreign-toplevel interface has no window-listing
  command, only match-and-act verbs, so it raises `ToolError` on the wlroots backend
- `get_windows` geometry is in KWin's logical (HiDPI-scaled) pixels, which can differ
  from the physical pixel space used by `screenshot`/mouse tools — see ROADMAP.md

## [0.2.0] - 2026-07-24

### Added

- `mouse_move`, `mouse_click`, `key_press`, `type_text` MCP tools via `ydotool`
- `ydotoold` runs as a user-level systemd unit (`~/.config/systemd/user/ydotoold.service`)
  rather than the packaged root-level system unit, so the daemon socket is usable by the
  desktop user without privilege escalation
- Linux keycode table (`keycodes.py`) sourced from `/usr/include/linux/input-event-codes.h`,
  with common aliases (`ctrl`, `enter`, `super`, etc.)

### Known limitations

- Synthetic `mouse_click` events do not reliably transfer KWin keyboard focus to the
  clicked window — see ROADMAP.md Phase 2 for details. Expected to be addressed by
  Phase 3's `focus_window`.

## [0.1.0] - 2026-07-24

### Added

- Initial project scaffold: `src/dual_wield_mcp` package, pyproject.toml, console entry point (`dual-wield-mcp`)
- Base server configuration schema (`ServerConfig`) with environment variable overrides
- `screenshot` MCP tool: full-desktop and region capture via `spectacle` (KDE's native
  screenshot tool — `grim`+`slurp` were evaluated first but do not work on KWin, which
  does not implement the `wlr-screencopy` protocol they depend on)
