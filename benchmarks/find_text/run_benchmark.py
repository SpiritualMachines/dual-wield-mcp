"""Standardized accuracy/latency benchmark for the find_text MCP tool.

Calls the real find_text code path (dual_wield_mcp.tools.ocr._find_text_in_image)
against a fixed set of fixture images with known ground truth, so results are
comparable across runs and reflect what actually ships, not a reimplementation.

This is deliberately separate from `pytest tests/`: it needs the real
`tesseract` binary, is noticeably slower than a mocked unit test, and is meant
to be run manually when validating an find_text-related change -- not on
every commit.

Usage:
    .venv/bin/python benchmarks/find_text/run_benchmark.py

See README.md in this directory for methodology, metric definitions, and how
to add a new case.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dual_wield_mcp import __version__
from dual_wield_mcp.tools.ocr import _find_text_in_image

BENCH_DIR = Path(__file__).parent
FIXTURES_DIR = BENCH_DIR / "fixtures"
CASES_PATH = BENCH_DIR / "cases.json"
RESULTS_PATH = BENCH_DIR / "RESULTS.md"

# A hit's center may land up to this many pixels outside the drawn text's own
# bbox and still count -- OCR word boxes are rarely pixel-exact even for a
# rendered fixture, and clicking is tolerant of a few stray pixels in practice.
HIT_PADDING = 5

# A matched line's bbox may be up to this multiple of the expected element's
# size and still count as "clean" (not silently merged with a neighbor while
# happening to still hit). Real OCR boxes are rarely pixel-exact, but a true
# cross-element merge (the bug this benchmark exists to catch) produces a
# bbox several times too wide, well outside this tolerance.
MERGE_TOLERANCE = 1.6


def _center_in_bbox(cx: float, cy: float, bbox: list[int]) -> bool:
    left, top, right, bottom = bbox
    return (left - HIT_PADDING <= cx <= right + HIT_PADDING) and (
        top - HIT_PADDING <= cy <= bottom + HIT_PADDING
    )


def _bbox_size_ok(match: dict, bbox: list[int]) -> bool:
    left, top, right, bottom = bbox
    expected_w, expected_h = right - left, bottom - top
    return (
        match["width"] <= expected_w * MERGE_TOLERANCE + 1
        and match["height"] <= expected_h * MERGE_TOLERANCE + 1
    )


def run_case(case: dict) -> dict:
    image_path = FIXTURES_DIR / case["image"]
    start = perf_counter()
    matches = _find_text_in_image(
        str(image_path), case["query"], case.get("case_sensitive", False), "tesseract"
    )
    elapsed_ms = (perf_counter() - start) * 1000

    expected_bboxes = case["expected_bboxes"]
    all_hit = True
    clean = True
    for bbox in expected_bboxes:
        covering = [m for m in matches if _center_in_bbox(m["center_x"], m["center_y"], bbox)]
        if not covering:
            all_hit = False
            continue
        if not any(_bbox_size_ok(m, bbox) for m in covering):
            clean = False

    # a generous upper bound on match count -- catches pathological
    # over-splitting without being brittle about exact OCR word-count noise
    reasonable_count = len(matches) <= max(len(expected_bboxes) * 2, 2)

    return {
        "id": case["id"],
        "known_limitation": case.get("known_limitation", False),
        "passed": all_hit and clean and reasonable_count,
        "all_hit": all_hit,
        "clean_bbox": clean,
        "reasonable_count": reasonable_count,
        "match_count": len(matches),
        "expected_count": len(expected_bboxes),
        "elapsed_ms": elapsed_ms,
    }


def _print_report(results: list[dict]) -> tuple[int, int, int, float]:
    print(f"dual-wield-mcp find_text benchmark -- v{__version__}")
    print(f"{'case':<34} {'status':<18} {'matches':<10} {'ms':>8}")
    print("-" * 74)
    for r in results:
        if r["known_limitation"]:
            status = "KNOWN LIMITATION"
        else:
            status = "PASS" if r["passed"] else "FAIL"
        counts = f"{r['match_count']}/{r['expected_count']}"
        print(f"{r['id']:<34} {status:<18} {counts:<10} {r['elapsed_ms']:>7.1f}")
        if not r["passed"] and not r["known_limitation"]:
            reasons = [
                name
                for name, ok in (
                    ("miss", r["all_hit"]),
                    ("merged/oversized bbox", r["clean_bbox"]),
                    ("too many matches", r["reasonable_count"]),
                )
                if not ok
            ]
            print(f"    -> {', '.join(reasons)}")

    scored = [r for r in results if not r["known_limitation"]]
    passed = [r for r in scored if r["passed"]]
    known = [r for r in results if r["known_limitation"]]
    avg_ms = sum(r["elapsed_ms"] for r in results) / len(results)

    print("-" * 74)
    print(f"Scored: {len(passed)}/{len(scored)} passed")
    print(f"Known limitations (not scored): {len(known)}")
    print(f"Average OCR latency: {avg_ms:.1f} ms/case")

    return len(passed), len(scored), len(known), avg_ms


def _append_results_log(passed_n: int, scored_n: int, known_n: int, avg_ms: float) -> None:
    header = "# find_text Benchmark Results\n\nAppend-only log, one row per run -- see README.md for methodology.\n\n"
    table_header = (
        "| Date | Version | Passed | Known limitations | Avg latency (ms) |\n"
        "|---|---|---|---|---|\n"
    )
    existing = RESULTS_PATH.read_text() if RESULTS_PATH.exists() else ""
    if table_header not in existing:
        existing = header + table_header

    rate = passed_n / scored_n if scored_n else 0.0
    today = datetime.now(UTC).date().isoformat()
    row = f"| {today} | {__version__} | {passed_n}/{scored_n} ({rate:.0%}) | {known_n} | {avg_ms:.1f} |\n"
    RESULTS_PATH.write_text(existing + row)
    print(f"\nAppended run to {RESULTS_PATH.relative_to(BENCH_DIR.parent.parent)}")


def main() -> int:
    cases = json.loads(CASES_PATH.read_text())
    results = [run_case(case) for case in cases]
    passed_n, scored_n, known_n, avg_ms = _print_report(results)
    _append_results_log(passed_n, scored_n, known_n, avg_ms)
    return 0 if passed_n == scored_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
