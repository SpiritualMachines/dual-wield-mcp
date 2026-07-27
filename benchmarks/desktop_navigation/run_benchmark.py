"""Desktop navigation benchmark for dual-wield-mcp.

Unlike benchmarks/find_text/, this is NOT a synthetic, pixel-reproducible
benchmark. It drives real applications (KWrite, Dolphin) on a real KDE
Plasma Wayland desktop through the actual MCP tools -- in-process via
mcp.call_tool(), against the real build_server(), so it exercises the same
code path a live agent session does (real spectacle/tesseract/ydotool/kdotool
subprocesses, real window manager behavior, real font rendering). What it
measures is whether the tool suite can complete realistic desktop-navigation
tasks end to end, not OCR accuracy in isolation -- that is find_text's job.

Requires: a running KDE Plasma Wayland session, ydotoold active, and kwrite
and dolphin installed. See README.md for the full methodology and the
findings this benchmark was built to track.
"""

import asyncio
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dual_wield_mcp import __version__
from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.server import build_server

FIXTURE_DIR = Path(__file__).parent / "fixture_dir"
FIXTURE_FILES = ["alpha_report.txt", "bravo_photo.png", "charlie_notes.md", "echo_archive.zip"]
FIXTURE_SUBDIR = "delta_folder"

WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H = 20, 20, 1100, 700


@dataclass
class Step:
    name: str
    ok: bool
    detail: str
    ms: float


@dataclass
class Scenario:
    name: str
    steps: list[Step] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)


def _text(result) -> str:
    return result[0].text


def _structured(result):
    return result[1]["result"]


def _parsed(result):
    return json.loads(result[0].text)


async def _call(mcp, name: str, args: dict):
    return await mcp.call_tool(name, args)


async def _step(
    scenario: Scenario, name: str, fn: Callable[[], Awaitable[tuple[bool, str]]]
) -> bool:
    """Run one check, time it, and record a Step. fn returns (ok, detail).

    A raised exception (e.g. a real ToolError from a tool call) is caught and
    recorded as a failed step instead of crashing the whole benchmark run --
    one broken step should not prevent the other scenario from reporting.
    """
    start = time.monotonic()
    try:
        ok, detail = await fn()
    except Exception as exc:  # noqa: BLE001 -- any tool failure must become a FAIL step, not a crash
        ms = (time.monotonic() - start) * 1000
        scenario.steps.append(Step(name, False, f"raised {type(exc).__name__}: {exc}", ms))
        return False
    ms = (time.monotonic() - start) * 1000
    scenario.steps.append(Step(name, ok, detail, ms))
    return ok


def _setup_fixture_dir() -> None:
    if FIXTURE_DIR.exists():
        shutil.rmtree(FIXTURE_DIR)
    FIXTURE_DIR.mkdir(parents=True)
    for name in FIXTURE_FILES:
        (FIXTURE_DIR / name).touch()
    (FIXTURE_DIR / FIXTURE_SUBDIR).mkdir()


def _check_prerequisites() -> list[str]:
    problems = []
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "ydotoold.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    if active.stdout.strip() != "active":
        problems.append(
            "ydotoold.service is not active -- mouse/keyboard tools will fail. "
            "Run: systemctl --user reset-failed ydotoold.service && "
            "systemctl --user start ydotoold.service"
        )
    for binary in ("kwrite", "dolphin"):
        if shutil.which(binary) is None:
            problems.append(f"{binary!r} not found on PATH -- required for this benchmark")
    return problems


async def run_kwrite_scenario(mcp) -> Scenario:
    scenario = Scenario("kwrite_menu_and_about")
    ctx: dict = {}

    async def launch():
        await _call(mcp, "launch_app", {"command": "kwrite"})
        return True, "launched kwrite"

    if not await _step(scenario, "launch_app", launch):
        return scenario

    async def wait():
        window = _parsed(
            await _call(mcp, "wait_for_window", {"window_class": "org.kde.kwrite", "timeout": 10.0})
        )
        ctx["window"] = window
        return True, window["title"]

    if not await _step(scenario, "wait_for_window", wait):
        return scenario

    try:
        window = ctx["window"]
        await _call(mcp, "move_window", {"window": window["id"], "x": WINDOW_X, "y": WINDOW_Y})
        await _call(
            mcp, "resize_window", {"window": window["id"], "width": WINDOW_W, "height": WINDOW_H}
        )

        async def menu_bar_check():
            await _call(mcp, "focus_window", {"window": window["id"]})
            path = _text(await _call(mcp, "screenshot", {"include_image": False}))
            lines = _structured(await _call(mcp, "read_screen_text", {"path": path}))
            bar = next(
                (line for line in lines if "File" in line["text"] and "Help" in line["text"]), None
            )
            return bar is not None, (bar["text"] if bar else "menu bar line not found")

        if not await _step(scenario, "menu_bar_reads_as_one_line", menu_bar_check):
            return scenario

        async def open_help_menu():
            await _call(mcp, "key_press", {"keys": "alt+h"})
            path = _text(await _call(mcp, "screenshot", {"include_image": False}))
            # scoped to the kwrite window: without this, the menu item's OCR
            # line can merge with unrelated text elsewhere on the desktop (see
            # README finding #2) instead of cleanly refusing or matching once
            matches = _structured(
                await _call(
                    mcp,
                    "find_text",
                    {"path": path, "query": "About KWrite", "window": window["id"]},
                )
            )
            ctx["about_menu_item"] = matches[0] if matches else None
            return len(matches) == 1, f"{len(matches)} in-window match(es)"

        if not await _step(scenario, "open_help_menu_via_mnemonic", open_help_menu):
            return scenario

        async def click_about():
            match = ctx["about_menu_item"]
            await _call(
                mcp, "mouse_move", {"x": int(match["center_x"]), "y": int(match["center_y"])}
            )
            await _call(mcp, "mouse_click", {"button": "left"})
            about_window = _parsed(
                await _call(mcp, "wait_for_window", {"title": "About KWrite", "timeout": 5.0})
            )
            ctx["about_window"] = about_window
            return True, "About KWrite dialog opened"

        if not await _step(scenario, "click_about_kwrite", click_about):
            return scenario

        async def read_about():
            # deliberately NOT window-scoped here: this step only needs to
            # read content, not disambiguate a click target, and a tighter
            # crop measurably loses content tesseract finds fine in full-page
            # context -- confirmed live, the dialog's two hyperlink-styled
            # lines ("License: ...", the kate-editor.org URL) are present in
            # a full-screenshot read but absent from a window-scoped read of
            # the exact same dialog. See README finding #7. window scoping is
            # for disambiguating a click target, not a strict superset of
            # full-page OCR.
            lines = _structured(await _call(mcp, "read_screen_text", {}))
            joined = " | ".join(line["text"] for line in lines)
            ok = "KWrite" in joined and "License" in joined
            return ok, f"{len(lines)} total line(s) on screen, dialog content present: {ok}"

        await _step(scenario, "read_about_dialog_content", read_about)

        async def close_about():
            about_window = ctx["about_window"]
            path = _text(await _call(mcp, "screenshot", {"include_image": False}))
            # scoped to the About dialog: this is the exact case that found a
            # real correctness gap pre-fix -- the real Close button merged
            # with unrelated text from a different window into one OCR line,
            # shifting the match's center outside the dialog entirely (see
            # README finding #2)
            matches = _structured(
                await _call(
                    mcp, "find_text", {"path": path, "query": "Close", "window": about_window["id"]}
                )
            )
            if len(matches) != 1:
                return False, f"expected exactly 1 in-window Close match, got {len(matches)}"
            match = matches[0]
            await _call(
                mcp, "mouse_move", {"x": int(match["center_x"]), "y": int(match["center_y"])}
            )
            await _call(mcp, "mouse_click", {"button": "left"})
            return True, "clicked Close"

        await _step(scenario, "close_about_dialog", close_about)
    finally:
        window = ctx.get("window")
        if window is not None:
            await _call(mcp, "close_window", {"window": window["id"]})

    return scenario


async def run_dolphin_scenario(mcp) -> Scenario:
    scenario = Scenario("dolphin_file_listing_and_navigation")
    ctx: dict = {}
    _setup_fixture_dir()

    async def launch():
        await _call(mcp, "launch_app", {"command": "dolphin", "args": [str(FIXTURE_DIR)]})
        return True, str(FIXTURE_DIR)

    if not await _step(scenario, "launch_app", launch):
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR)
        return scenario

    async def wait():
        window = _parsed(
            await _call(
                mcp, "wait_for_window", {"window_class": "org.kde.dolphin", "timeout": 10.0}
            )
        )
        ctx["window"] = window
        return True, window["title"]

    if not await _step(scenario, "wait_for_window", wait):
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR)
        return scenario

    try:
        window = ctx["window"]
        await _call(mcp, "move_window", {"window": window["id"], "x": WINDOW_X, "y": WINDOW_Y})
        await _call(
            mcp, "resize_window", {"window": window["id"], "width": WINDOW_W, "height": WINDOW_H}
        )

        async def bulk_read():
            lines = _structured(await _call(mcp, "read_screen_text", {"window": window["id"]}))
            joined = " | ".join(line["text"] for line in lines)
            expected = [*FIXTURE_FILES, FIXTURE_SUBDIR]
            found = [name for name in expected if name in joined]
            missing = [name for name in expected if name not in joined]
            # allow one known-garbled name -- see README (image thumbnail rows)
            ok = len(found) >= len(expected) - 1
            return ok, f"found {found}, missing {missing}"

        await _step(scenario, "bulk_read_file_listing", bulk_read)

        async def navigate():
            path = _text(await _call(mcp, "screenshot", {"include_image": False}))
            matches = _structured(
                await _call(
                    mcp,
                    "find_text",
                    {"path": path, "query": FIXTURE_SUBDIR, "window": window["id"]},
                )
            )
            # the file-listing entry is not the only in-window match (the
            # breadcrumb/tab can also show the current folder name); the
            # highest-confidence match is find_text's own ranking, same as a
            # caller would use in practice
            if not matches:
                return False, f"{FIXTURE_SUBDIR!r} not found in dolphin's window"
            match = matches[0]
            cx, cy = int(match["center_x"]), int(match["center_y"])
            await _call(mcp, "mouse_move", {"x": cx, "y": cy})
            # double=True: a single mouse_click here only selects the item in
            # this list view (double-click-to-open is the configured
            # default) -- confirmed live that two separate mouse_click calls
            # don't register as a double-click at all (see README finding #4)
            await _call(mcp, "mouse_click", {"button": "left", "double": True})
            active = _parsed(await _call(mcp, "get_active_window", {}))
            ok = active["title"].startswith(FIXTURE_SUBDIR)
            return ok, f"active window title: {active['title']!r}"

        await _step(scenario, "navigate_into_folder", navigate)
    finally:
        window = ctx.get("window")
        if window is not None:
            await _call(mcp, "close_window", {"window": window["id"]})
        if FIXTURE_DIR.exists():
            shutil.rmtree(FIXTURE_DIR)

    return scenario


def _print_report(scenarios: list[Scenario]) -> None:
    print(f"dual-wield-mcp desktop navigation benchmark -- v{__version__}")
    print(f"{'scenario / step':<45} {'status':<8} {'ms':>8}  detail")
    print("-" * 110)
    for scenario in scenarios:
        print(f"{scenario.name:<45} {'PASS' if scenario.passed else 'FAIL':<8}")
        for step in scenario.steps:
            status = "ok" if step.ok else "FAIL"
            print(f"  - {step.name:<41} {status:<8} {step.ms:>6.0f}ms  {step.detail}")
    print("-" * 110)
    total_ms = sum(s.ms for scenario in scenarios for s in scenario.steps)
    print(f"Total wall-clock across all steps: {total_ms / 1000:.1f}s")


def _append_results(scenarios: list[Scenario]) -> None:
    results_path = Path(__file__).parent / "RESULTS.md"
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [f"\n## {timestamp} -- v{__version__}\n"]
    for scenario in scenarios:
        status = "PASS" if scenario.passed else "FAIL"
        lines.append(f"- **{scenario.name}**: {status}")
        for step in scenario.steps:
            lines.append(
                f"  - {step.name}: {'ok' if step.ok else 'FAIL'} ({step.ms:.0f}ms) -- {step.detail}"
            )
    with results_path.open("a") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nAppended run to {results_path}")


async def main() -> int:
    problems = _check_prerequisites()
    if problems:
        print("Cannot run benchmark:")
        for p in problems:
            print(f"  - {p}")
        return 1

    config = ServerConfig.from_env()
    mcp = build_server(config)
    scenarios = [
        await run_kwrite_scenario(mcp),
        await run_dolphin_scenario(mcp),
    ]

    _print_report(scenarios)
    _append_results(scenarios)

    return 0 if all(s.passed for s in scenarios) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
