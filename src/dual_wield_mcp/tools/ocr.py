import logging
from itertools import pairwise
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from dual_wield_mcp.config import ServerConfig
from dual_wield_mcp.tools.input import _get_display_scale
from dual_wield_mcp.tools.screenshot import _capture_screenshot
from dual_wield_mcp.tools.window import _detect_backend, _kde_resolve_window_geometry

logger = logging.getLogger(__name__)

# Split words sharing a tesseract line_num into separate results when the
# horizontal gap between them exceeds this multiple of their height. Grid
# layouts (icon labels, toolbar buttons) routinely place unrelated text at the
# same y-coordinate, which tesseract reports as one line_num even though the
# words are separated by a full column width — far more than the small
# inter-word gap of an actual sentence or phrase. Confirmed live: a KDE app
# launcher's icon row OCR'd as a single line ("Firefox Steam VeraCrypt
# ClamTk"), making the returned center coordinate useless for any one label.
_LINE_SPLIT_GAP_RATIO = 2.5


def _group_words_into_lines(data: dict) -> list[dict]:
    # pytesseract's image_to_data returns one row per detected word; a multi-word
    # phrase (e.g. a two-word button label) only becomes substring-matchable if
    # words sharing a line are joined back together first, keyed by the
    # (block, paragraph, line) triple tesseract itself assigns them
    raw_lines: dict[tuple[int, int, int], list[dict]] = {}
    for i in range(len(data["text"])):
        word = data["text"][i].strip()
        if not word or float(data["conf"][i]) < 0:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left, top = data["left"][i], data["top"][i]
        raw_lines.setdefault(key, []).append(
            {
                "word": word,
                "left": left,
                "top": top,
                "right": left + data["width"][i],
                "bottom": top + data["height"][i],
                "conf": float(data["conf"][i]),
            }
        )

    results = []
    for words in raw_lines.values():
        words.sort(key=lambda w: w["left"])
        for run in _split_on_gaps(words):
            results.append(_line_from_words(run))
    return results


def _split_on_gaps(words: list[dict]) -> list[list[dict]]:
    # words must already be sorted left-to-right
    runs = [[words[0]]]
    for prev, word in pairwise(words):
        height = max(prev["bottom"] - prev["top"], word["bottom"] - word["top"])
        gap = word["left"] - prev["right"]
        if gap > height * _LINE_SPLIT_GAP_RATIO:
            runs.append([])
        runs[-1].append(word)
    return runs


def _line_from_words(words: list[dict]) -> dict:
    left = min(w["left"] for w in words)
    top = min(w["top"] for w in words)
    right = max(w["right"] for w in words)
    bottom = max(w["bottom"] for w in words)
    confidences = [w["conf"] for w in words]
    return {
        "text": " ".join(w["word"] for w in words),
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "center_x": (left + right) // 2,
        "center_y": (top + bottom) // 2,
        "confidence": sum(confidences) / len(confidences),
    }


def _ocr_lines_from_pil_image(image: PILImage.Image, tesseract_path: str) -> list[dict]:
    # core OCR call shared by the whole-file path below and by the
    # window-scoped path (which OCRs an in-memory crop, never written to disk)
    try:
        import pytesseract
    except ImportError as exc:
        raise ToolError(f"pytesseract is not installed: {exc}") from exc

    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as exc:
        raise ToolError(f"tesseract binary not found at {tesseract_path!r}: {exc}") from exc

    return _group_words_into_lines(data)


def _load_image(path: str) -> PILImage.Image:
    src = Path(path).expanduser()
    if not src.is_file():
        raise ToolError(f"no such file: {src}")
    try:
        return PILImage.open(src)
    except UnidentifiedImageError as exc:
        raise ToolError(f"{src} is not a readable image: {exc}") from exc


def _ocr_lines_from_image(path: str, tesseract_path: str) -> list[dict]:
    # shared by find_text and read_screen_text below, and by
    # benchmarks/find_text/run_benchmark.py, so the benchmark measures this
    # exact code path rather than a reimplementation that could silently
    # drift from what actually ships
    image = _load_image(path)
    return _ocr_lines_from_pil_image(image, tesseract_path)


def _ocr_lines_in_window(path: str, config: ServerConfig, window: str) -> list[dict]:
    # OCRs only the given window's region instead of the whole screenshot, so
    # unrelated text elsewhere on the desktop (most commonly the calling
    # agent's own terminal, which is always visible somewhere and routinely
    # echoes back the exact text it's about to search for) can neither
    # produce a spurious extra match nor -- more seriously -- get merged by
    # the gap-splitting grouping above into the SAME line as real text from
    # the target window, silently shifting that match's center point outside
    # where it actually is. Found live: an About dialog's real "Close" button
    # merged with unrelated terminal text sitting nearby on screen into one
    # OCR line, pulling the match's center outside the dialog entirely --
    # exactly the failure mode this exists to prevent.
    if _detect_backend(config) != "kde":
        raise ToolError(
            "window-scoped OCR is only supported on the KDE backend (via kdotool): "
            "wlrctl has no per-window geometry query"
        )

    info = _kde_resolve_window_geometry(config, window)
    scale = _get_display_scale(config)
    x0, y0 = info.x * scale, info.y * scale
    x1, y1 = x0 + info.width * scale, y0 + info.height * scale

    image = _load_image(path)
    img_width, img_height = image.size
    left, top = max(0, int(x0)), max(0, int(y0))
    right, bottom = min(img_width, int(x1)), min(img_height, int(y1))
    if right <= left or bottom <= top:
        raise ToolError(
            f"window {window!r}'s bounds ({left},{top})-({right},{bottom}) do not "
            f"overlap the screenshot ({img_width}x{img_height}) -- was it captured "
            "before the window moved, or from a different display state?"
        )

    cropped = image.crop((left, top, right, bottom))
    lines = _ocr_lines_from_pil_image(cropped, config.tesseract_path)
    # translate crop-relative coordinates back to absolute physical-pixel
    # screen space, the same space every other tool's coordinates are in
    for line in lines:
        line["x"] += left
        line["y"] += top
        line["center_x"] += left
        line["center_y"] += top
    return lines


def _find_text_in_image(
    path: str, query: str, case_sensitive: bool, tesseract_path: str
) -> list[dict]:
    if not query:
        raise ToolError("query must not be empty")

    needle = query if case_sensitive else query.lower()
    matches = [
        line
        for line in _ocr_lines_from_image(path, tesseract_path)
        if needle in (line["text"] if case_sensitive else line["text"].lower())
    ]
    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches


def _find_text_in_window(
    path: str, query: str, case_sensitive: bool, config: ServerConfig, window: str
) -> list[dict]:
    if not query:
        raise ToolError("query must not be empty")

    needle = query if case_sensitive else query.lower()
    matches = [
        line
        for line in _ocr_lines_in_window(path, config, window)
        if needle in (line["text"] if case_sensitive else line["text"].lower())
    ]
    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches


def register_ocr_tools(mcp: FastMCP, config: ServerConfig) -> None:
    @mcp.tool()
    def find_text(
        path: str, query: str, case_sensitive: bool = False, window: str | None = None
    ) -> list[dict]:
        """Locate text in a screenshot via OCR, returning clickable coordinates.

        Runs local OCR (tesseract) over an existing screenshot and returns
        every detected line of text containing query as a substring, with a
        bounding box and center point in the same physical-pixel space
        screenshot/mouse_move/mouse_click use — so a match can be clicked
        directly (mouse_move to center_x/center_y, then mouse_click) instead
        of visually estimating coordinates from a crop. This is the typical
        way to find a specific labeled button, link, or menu item without a
        manual screenshot -> inspect_region -> eyeball-the-pixel loop.

        OCR is not infallible: it can misread small or stylized text, and a
        substring match does not guarantee the line is the intended target if
        the page repeats similar text (e.g. several video titles containing
        the same word). Treat a single high-confidence match as safe to act
        on directly; for multiple matches or low confidence, fall back to a
        screenshot/inspect_region visual check before clicking.

        Args:
            path: path to an existing image file, typically a prior
                screenshot call's returned path.
            query: substring to search for within each detected line of text.
            case_sensitive: if False (default), matching ignores case.
            window: optional window id (from get_windows) or title substring.
                When given, only OCRs that window's region instead of the
                whole screenshot, and returns coordinates translated back to
                absolute screen space. Use this whenever query text might
                also appear elsewhere on the desktop -- most commonly the
                calling agent's own visible terminal, which routinely echoes
                back the exact text it's about to search for. This is
                stronger than filtering matches by window bounds afterward:
                without scoping, OCR can merge real text from the target
                window with unrelated text from a different window into one
                line, silently shifting the match's center point outside the
                intended window entirely rather than producing a clean
                "multiple matches" refusal. KDE backend only.
        """
        if window is not None:
            matches = _find_text_in_window(path, query, case_sensitive, config, window)
        else:
            matches = _find_text_in_image(path, query, case_sensitive, config.tesseract_path)
        logger.info("find_text(%r) in %s: %d match(es)", query, path, len(matches))
        return matches

    @mcp.tool()
    def read_screen_text(path: str | None = None, window: str | None = None) -> list[dict]:
        """Read every line of text visible in a screenshot via OCR, with positions.

        Like find_text but with no query filter -- returns every detected
        line (grouped the same way, split on wide horizontal gaps so
        unrelated UI elements don't merge into one line), sorted top-to-bottom
        then left-to-right, instead of only lines containing a substring.

        Use this to read a whole board, grid, or list in one call instead of
        visually parsing several inspect_region crops or calling find_text
        once per possible value -- e.g. every revealed number in a
        minesweeper-style grid, or every row of a file list, in a single
        structured pass rather than eyeballing crops cell by cell.

        Captures a fresh full-desktop screenshot if path is not given.

        Args:
            path: optional path to an existing screenshot, typically a prior
                screenshot call's returned path. Captures a fresh
                full-desktop screenshot if omitted.
            window: optional window id (from get_windows) or title substring.
                When given, only OCRs and returns lines from that window's
                region, translated back to absolute screen space -- same
                semantics as find_text's window parameter. Use this to read
                one window's content without unrelated text from elsewhere on
                the desktop appearing in the results. KDE backend only.
        """
        image_path = path if path is not None else str(_capture_screenshot(config, "full", None))
        if window is not None:
            lines = _ocr_lines_in_window(image_path, config, window)
        else:
            lines = _ocr_lines_from_image(image_path, config.tesseract_path)
        lines.sort(key=lambda line: (line["y"], line["x"]))
        logger.info("read_screen_text(%s): %d line(s)", image_path, len(lines))
        return lines
