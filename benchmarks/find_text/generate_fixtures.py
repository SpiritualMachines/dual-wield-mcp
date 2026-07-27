"""Generate find_text benchmark fixture images and their ground-truth manifest.

Fixtures are synthetic (not real desktop screenshots) so the benchmark is
reproducible across machines and doesn't depend on the live desktop's
changing state (open apps, YouTube video, file listings) or capture personal
screen content into a committed file. Cases are still shaped to reproduce
the real failure patterns found live -- see README.md for the incident this
benchmark exists to track.

Re-run this script whenever a case is added or changed:

    .venv/bin/python benchmarks/find_text/generate_fixtures.py

It regenerates every fixture PNG and rewrites cases.json from scratch, so
ground-truth boxes are always taken directly from what PIL actually drew
(via ImageDraw.textbbox), never guessed or hand-transcribed.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CASES_PATH = Path(__file__).parent / "cases.json"

# PIL's bundled scalable default font -- no system/font-package dependency,
# confirmed to OCR cleanly with the real tesseract binary (see README.md).
FONT = ImageFont.load_default(size=22)
SMALL_FONT = ImageFont.load_default(size=12)

_cases = []


def _new_image(size):
    return Image.new("RGB", size, "white")


def _draw_label(draw, text, x, y, font=FONT):
    bbox = draw.textbbox((x, y), text, font=font)
    draw.text((x, y), text, fill="black", font=font)
    return list(bbox)


def _add_case(**case):
    _cases.append(case)


def make_icon_grid_kickoff():
    # Reproduces the KDE Kickoff app-launcher favorites row that originally
    # OCR'd as a single line ("a Firefox Steam VeraCrypt ClamTk"), making the
    # returned center coordinate land under the wrong icon entirely.
    img = _new_image((1000, 260))
    draw = ImageDraw.Draw(img)
    boxes = {}
    for text, x in [("Firefox", 40), ("Steam", 260), ("VeraCrypt", 480), ("ClamTk", 720)]:
        boxes[text] = _draw_label(draw, text, x, 150)
    path = FIXTURES_DIR / "icon_grid_kickoff.png"
    img.save(path)

    _add_case(
        id="icon_grid_kickoff_clamtk",
        image=path.name,
        query="ClamTk",
        case_sensitive=False,
        category="icon_grid",
        known_limitation=False,
        expected_bboxes=[boxes["ClamTk"]],
        notes="Rightmost of 4 icon labels on one row; must not merge with its neighbors.",
    )
    _add_case(
        id="icon_grid_kickoff_steam",
        image=path.name,
        query="Steam",
        case_sensitive=False,
        category="icon_grid",
        known_limitation=False,
        expected_bboxes=[boxes["Steam"]],
        notes="A middle-column label, flanked on both sides -- the harder case for gap-splitting.",
    )


def make_icon_grid_clamtk_config():
    # Direct recreation of the actual ClamTk "Configuration" row from the
    # live incident: Settings / Whitelist / Network / Scheduler.
    img = _new_image((900, 260))
    draw = ImageDraw.Draw(img)
    boxes = {}
    for text, x in [("Settings", 40), ("Whitelist", 260), ("Network", 480), ("Scheduler", 700)]:
        boxes[text] = _draw_label(draw, text, x, 150)
    path = FIXTURES_DIR / "icon_grid_clamtk_config.png"
    img.save(path)

    _add_case(
        id="icon_grid_clamtk_settings",
        image=path.name,
        query="Settings",
        case_sensitive=False,
        category="icon_grid",
        known_limitation=False,
        expected_bboxes=[boxes["Settings"]],
        notes="Leftmost label of the exact row that failed during the live ClamTk test.",
    )
    _add_case(
        id="icon_grid_clamtk_scheduler",
        image=path.name,
        query="Scheduler",
        case_sensitive=False,
        category="icon_grid",
        known_limitation=False,
        expected_bboxes=[boxes["Scheduler"]],
        notes="Rightmost label of the same row.",
    )


def make_multiword_phrase():
    # A single UI element with a natural multi-word label (tight inter-word
    # spacing) -- must still merge into one match, unlike the icon-grid cases.
    img = _new_image((500, 150))
    draw = ImageDraw.Draw(img)
    bbox = _draw_label(draw, "Engine Driver", 40, 60)
    path = FIXTURES_DIR / "multiword_phrase.png"
    img.save(path)

    _add_case(
        id="multiword_phrase_engine_driver",
        image=path.name,
        query="Engine Driver",
        case_sensitive=False,
        category="prose",
        known_limitation=False,
        expected_bboxes=[bbox],
        notes="Two words of one phrase, normal inter-word gap -- must stay merged into one match.",
    )


def make_dense_list():
    # A file-browser-style list: several full rows, well separated vertically.
    # Tests substring matching across multiple structurally similar lines and
    # that adjacent rows never merge into each other.
    img = _new_image((700, 400))
    draw = ImageDraw.Draw(img)
    rows = [
        "invoice_2024.pdf",
        "report_draft.docx",
        "report_final.pdf",
        "budget.xlsx",
        "notes.txt",
        "report_appendix.pdf",
    ]
    boxes = {}
    y = 30
    for text in rows:
        boxes[text] = _draw_label(draw, text, 40, y)
        y += 50
    path = FIXTURES_DIR / "dense_list.png"
    img.save(path)

    _add_case(
        id="dense_list_single_match",
        image=path.name,
        query="invoice",
        case_sensitive=False,
        category="list",
        known_limitation=False,
        expected_bboxes=[boxes["invoice_2024.pdf"]],
        notes="Substring unique to one row among several similar-looking rows.",
    )
    _add_case(
        id="dense_list_multi_match",
        image=path.name,
        query="report",
        case_sensitive=False,
        category="list",
        known_limitation=False,
        expected_bboxes=[
            boxes["report_draft.docx"],
            boxes["report_final.pdf"],
            boxes["report_appendix.pdf"],
        ],
        notes="Substring shared by 3 non-adjacent-in-value rows -- each must resolve to its own row, none merged.",
    )


def make_close_together_labels():
    # Two short, genuinely distinct UI elements (e.g. a Yes/No toggle) placed
    # with a deliberately small gap -- smaller than the gap-splitting
    # threshold. Known limitation: today's implementation has no signal other
    # than horizontal distance, so this currently merges into one match.
    # Kept in the benchmark (scored separately, not counted against the pass
    # rate) so a future improvement's impact on this exact case is visible.
    img = _new_image((300, 150))
    draw = ImageDraw.Draw(img)
    yes_box = _draw_label(draw, "Yes", 40, 60)
    no_box = _draw_label(draw, "No", 90, 60)
    path = FIXTURES_DIR / "close_together_labels.png"
    img.save(path)

    _add_case(
        id="close_together_yes_no",
        image=path.name,
        query="Yes",
        case_sensitive=False,
        category="edge_case",
        known_limitation=True,
        expected_bboxes=[yes_box],
        notes=(
            "Two distinct short labels closer together than the gap threshold; "
            f"currently merges with the adjacent 'No' label at {no_box}."
        ),
    )


def make_small_stylized_text():
    # Smaller font, testing OCR/confidence behavior on harder-to-read text
    # rather than the grouping logic specifically.
    img = _new_image((300, 120))
    draw = ImageDraw.Draw(img)
    bbox = _draw_label(draw, "Details", 30, 50, font=SMALL_FONT)
    path = FIXTURES_DIR / "small_stylized_text.png"
    img.save(path)

    _add_case(
        id="small_stylized_text_details",
        image=path.name,
        query="Details",
        case_sensitive=False,
        category="small_text",
        known_limitation=False,
        expected_bboxes=[bbox],
        notes="12px text -- checks OCR still resolves a small label correctly.",
    )


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    make_icon_grid_kickoff()
    make_icon_grid_clamtk_config()
    make_multiword_phrase()
    make_dense_list()
    make_close_together_labels()
    make_small_stylized_text()

    CASES_PATH.write_text(json.dumps(_cases, indent=2) + "\n")
    print(f"Wrote {len(_cases)} cases across {len({c['image'] for c in _cases})} fixture images")


if __name__ == "__main__":
    main()
