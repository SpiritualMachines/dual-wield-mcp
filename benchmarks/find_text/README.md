# find_text Benchmark

A standardized accuracy/latency benchmark for the `find_text` MCP tool
(`src/dual_wield_mcp/tools/ocr.py`), so a change to its OCR grouping logic can
be checked against a fixed baseline instead of relying on one-off live
testing.

## Why this exists

`find_text` was added in v1.4.0 and immediately hit a real accuracy bug the
same session, during a live ClamTk test: OCR grouped several unrelated
icon-grid labels ("Settings Whitelist Network Scheduler") into a single line,
making the returned center coordinate land under the wrong icon. v1.4.1 fixed
this by splitting a tesseract line wherever the horizontal gap between
adjacent words exceeds `_LINE_SPLIT_GAP_RATIO` (2.5x their height). This
benchmark exists to answer, precisely, "did that fix work, and does the next
change to this code make things better or worse" — the underlying live-test
failure prompted the fix, but a live desktop isn't a repeatable test surface
(open windows, video content, and file listings all change between runs).

## Design choices

- **Fixtures are synthetic, not real screenshots.** Cases are shaped to
  reproduce the real failure patterns observed live (see `generate_fixtures.py`
  docstrings for which case maps to which incident), but are rendered
  deterministically with PIL rather than captured from the desktop. This
  keeps the benchmark reproducible across machines and over time, and avoids
  committing personal screen content (file listings, browsing history) into
  version control.
- **The benchmark calls the real code path.** `run_benchmark.py` imports
  `_find_text_in_image` directly from `dual_wield_mcp.tools.ocr` — the same
  function the MCP tool calls — so it measures what actually ships, not a
  reimplementation that could quietly drift out of sync.
- **Ground truth is generated, not hand-transcribed.** `generate_fixtures.py`
  reads each drawn label's bounding box straight from
  `ImageDraw.textbbox(...)` at render time and writes it into `cases.json`.
  There is no manual pixel-guessing to get wrong.
- **Separate from `pytest tests/`.** This needs the real `tesseract` binary
  and is slower than a mocked unit test (~150-250ms per case vs. instant for
  a mock). Run it manually when changing OCR-related code, not on every
  commit — `tests/test_ocr.py` covers the grouping algorithm itself with fast
  mocked data.

## Running it

```bash
.venv/bin/python benchmarks/find_text/run_benchmark.py
```

Exits non-zero if any non-`known_limitation` case fails, so it can be used as
a gate (e.g. before tagging a release that touches `tools/ocr.py`). Prints a
per-case report and appends a summary row to `RESULTS.md`.

To regenerate fixtures after adding or editing a case in
`generate_fixtures.py`:

```bash
.venv/bin/python benchmarks/find_text/generate_fixtures.py
```

## Scoring

Each case in `cases.json` lists one or more `expected_bboxes` — the exact
pixel box of a UI element `find_text` should be able to locate. A case
passes when, for every expected box:

- **hit** — at least one returned match's `(center_x, center_y)` falls
  inside the box (padded by `HIT_PADDING = 5px`, since OCR word boxes are
  rarely pixel-exact even for a rendered fixture).
- **clean bbox** — the hitting match's own `width`/`height` isn't more than
  `MERGE_TOLERANCE = 1.6x` the expected box's size. This is the check that
  actually catches the original bug class: a match can technically "hit" by
  landing inside the right box while still being an oversized, merged line
  spanning several unrelated labels — clean-bbox catches that even when the
  center-point happens to still fall in the right place.
- **reasonable match count** — total matches returned isn't wildly more than
  the number of expected boxes (catches pathological over-splitting).

Cases marked `"known_limitation": true` are run and reported but excluded
from the pass rate — they document a real, currently-unsolved tradeoff (see
`close_together_labels` below) rather than a regression to fix immediately.
Marking something a known limitation should be a deliberate, documented
choice, not a way to make a case stop failing.

## Current cases

| id | category | tests |
|---|---|---|
| `icon_grid_kickoff_clamtk` / `_steam` | icon_grid | KDE app-launcher-style row, 4 labels, edge and middle columns |
| `icon_grid_clamtk_settings` / `_scheduler` | icon_grid | Exact recreation of the row that failed live |
| `multiword_phrase_engine_driver` | prose | A real multi-word phrase must stay merged (regression guard against over-splitting) |
| `dense_list_single_match` | list | Substring unique to one row among several similar rows |
| `dense_list_multi_match` | list | Substring shared by 3 non-adjacent rows — each must resolve separately |
| `close_together_yes_no` | edge_case | **Known limitation** — two distinct short labels closer together than the gap threshold currently merge |
| `small_stylized_text_details` | small_text | 12px text |

## Known findings so far

- **`close_together_yes_no` (known limitation):** the gap-ratio heuristic has
  no signal besides horizontal distance, so two genuinely distinct short
  labels placed close together (e.g. a tight Yes/No toggle) still merge. Not
  currently scored as a failure since there's no obvious fix without a
  different signal entirely (e.g. detecting a widget boundary, which is out
  of reach for tesseract's plain OCR output).
- **`small_stylized_text_details` (real failure, first run 2026-07-26):**
  tesseract misread 12px "Details" as "Detalls" (confidence 87), so the
  substring match missed entirely. This is a genuine tesseract accuracy
  limitation at small font sizes, not a grouping bug — and unlike the
  known-limitation case above, it looks addressable (e.g. upscaling a region
  before OCR). Left as a scored failure rather than exempted, since it's a
  real gap worth targeting in a future pass, and exempting it would make the
  benchmark stop tracking whether it ever gets fixed.

## Adding a case

1. Add a `make_*()` function to `generate_fixtures.py` that draws a fixture
   image and calls `_add_case(...)` with the query, `expected_bboxes` (from
   `_draw_label`'s return value), a `category`, and `notes` explaining what
   real-world pattern it represents.
2. Run `generate_fixtures.py` to produce the image and rewrite `cases.json`.
3. Run `run_benchmark.py` and confirm the new case's result matches what you
   expect (a case you expect to currently fail should be marked
   `known_limitation: true` with a note explaining why, per the rule above).
