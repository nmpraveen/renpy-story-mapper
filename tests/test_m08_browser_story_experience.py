from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
ASSETS = ("index.html", "styles.css", "app.js", "api.js", "contract.js")


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _assets() -> str:
    return "\n".join(_text(name) for name in ASSETS)


def test_editorial_cartography_is_local_restrained_and_free_of_mojibake() -> None:
    assets = _assets()
    css = _text("styles.css")
    assert "Georgia" in css and "Segoe UI" in css
    assert "--paper:" in css and "--ink:" in css and "--accent:" in css
    assert "linear-gradient" not in css and "radial-gradient" not in css
    assert not re.search(r"Ã|Â|â|�|[\u0080-\u009f]", assets)
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert ".card-grid" not in css


def test_reader_surface_names_the_story_not_the_milestone() -> None:
    assert not re.search(r"\bLevel\s*[123]\b", _assets(), re.IGNORECASE)
    html = _text("index.html")
    for milestone in ("M07 Structure", "M10 Inspection", "AI Story Map", "Narrative jobs"):
        assert milestone not in html, milestone


def test_progress_and_generation_language_stays_honest() -> None:
    html = _text("index.html")
    assert "Reading story structure" in html
    assert 'id="storyRunState"' in html and 'id="storyRunProgress"' in html
    assert "Zero-submit preview" in html
    assert 'id="approveStoryGeneration"' in html
