"""AI-vision OCR tests for the iteration-3 change.

Verifies:
- POST /api/extract returns engine=='ai' with clean text for a handwriting-style
  English image (uses an oblique/italic font as a stand-in for cursive script).
- POST /api/extract preserves Bengali script for a Bengali image (Lohit / Noto
  Bengali on the container) and returns engine=='ai'.
- One-pass cleanup: no commentary preamble like "here is", "sure,", "note:" and
  no translation to English for the Bengali image.
- History record is created on each successful extraction.
- POST /api/quality-check is handwriting-aware: an image containing only
  handwriting-style strokes must return has_text=true and NOT include the
  'no_text' issue.
- Regression: blank image STILL flags no_text.
"""
import io
import os
from pathlib import Path

import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL"
) else "https://docx-capture.preview.emergentagent.com"
API = f"{BASE_URL}/api"


def _find_font(candidates):
    for p in candidates:
        if Path(p).exists():
            return p
    return None


ENGLISH_HANDWRITING_FONTS = [
    "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

BENGALI_FONTS = [
    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Bold.ttf",
    "/usr/share/fonts/truetype/fonts-beng-extra/MitraMono.ttf",
]


def _render_text_image(text: str, font_path: str, size=(1000, 500), font_size=64) -> bytes:
    """Render dark text on a slightly off-white page — realistic ink features."""
    img = Image.new("RGB", size, (250, 248, 244))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    # Multi-line: split roughly to leave headroom & margins
    lines = text.split("\n")
    y = 60
    for ln in lines:
        d.text((60, y), ln, fill=(20, 20, 30), font=font)
        y += int(font_size * 1.4)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _handwriting_only_image() -> bytes:
    """Cursive-styled text image — no blank/solid frame, real strokes."""
    font_path = _find_font(ENGLISH_HANDWRITING_FONTS)
    assert font_path, "No italic/oblique font available to simulate handwriting"
    return _render_text_image(
        "The quick brown fox\njumps over the lazy dog\nHello handwriting",
        font_path,
        font_size=72,
    )


def _bengali_image() -> bytes:
    font_path = _find_font(BENGALI_FONTS)
    assert font_path, "No Bengali font installed"
    # "Amar sonar Bangla / I love Bengali language" (common test phrase)
    return _render_text_image(
        "আমার সোনার বাংলা\nআমি তোমায় ভালোবাসি",
        font_path,
        font_size=64,
    )


def _blank_image() -> bytes:
    img = Image.new("RGB", (600, 400), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def session():
    return requests.Session()


# ---------- /api/extract engine=='ai' ----------
class TestExtractAIEngine:
    """Vision-primary OCR (Gemini 3 Flash)."""

    def test_english_handwriting_returns_ai_engine_with_readable_text(self, session):
        img = _handwriting_only_image()
        r = session.post(
            f"{API}/extract",
            files={"file": ("hw_en.jpg", img, "image/jpeg")},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(["id", "text", "engine"]).issubset(data.keys()), data
        assert data["engine"] in {"gemma", "gemini"}, f"Expected an AI engine, got {data['engine']}: {data['text']!r}"
        text_lower = data["text"].lower()
        # At least two of the expected key words should be present — vision is not exact
        expected_words = ["quick", "brown", "fox", "lazy", "dog", "handwriting", "hello"]
        hits = sum(1 for w in expected_words if w in text_lower)
        assert hits >= 3, f"Expected >=3 key words to appear, got {hits}: {data['text']!r}"
        # No commentary preamble
        for banned in ["here is", "the text reads", "transcription:", "sure,", "note:", "```"]:
            assert banned not in text_lower, f"Commentary detected ({banned}): {data['text']!r}"
        # No translation appended in parentheses (rough heuristic)
        assert "translation" not in text_lower

    def test_bengali_stays_bengali_and_engine_ai(self, session):
        img = _bengali_image()
        r = session.post(
            f"{API}/extract",
            files={"file": ("hw_bn.jpg", img, "image/jpeg")},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["engine"] in {"gemma", "gemini"}, f"Expected an AI engine, got {data}"
        text = data["text"]
        # Must contain Bengali characters (U+0980–U+09FF)
        has_bengali = any("\u0980" <= c <= "\u09FF" for c in text)
        assert has_bengali, f"Bengali script missing (translated?): {text!r}"
        # Should be reasonably long, not a NO_TEXT_FOUND flag
        assert len(text.strip()) >= 4, f"Text too short: {text!r}"
        # No English translation glosses
        text_lower = text.lower()
        for banned in ["translation", "means", "in english"]:
            assert banned not in text_lower, f"Model added translation gloss: {text!r}"

    def test_history_grows_after_ai_extract(self, session):
        # snapshot
        pre = session.get(f"{API}/history").json()
        pre_ids = {i["id"] for i in pre}
        img = _handwriting_only_image()
        r = session.post(
            f"{API}/extract",
            files={"file": ("hw_hist.jpg", img, "image/jpeg")},
            timeout=90,
        )
        assert r.status_code == 200
        new_id = r.json()["id"]
        post = session.get(f"{API}/history").json()
        post_ids = {i["id"] for i in post}
        assert new_id in post_ids, "new extract not visible in history"
        assert new_id not in pre_ids
        # cleanup
        session.delete(f"{API}/history/{new_id}")


# ---------- handwriting-aware /api/quality-check ----------
class TestQualityCheckHandwritingAware:
    def test_handwriting_image_has_text_true(self, session):
        img = _handwriting_only_image()
        r = session.post(
            f"{API}/quality-check",
            files={"file": ("hw_q.jpg", img, "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        codes = {i["code"] for i in data["issues"]}
        assert "no_text" not in codes, f"handwriting incorrectly flagged as no_text: {data}"
        assert data["has_text"] is True, data

    def test_bengali_image_has_text_true(self, session):
        img = _bengali_image()
        r = session.post(
            f"{API}/quality-check",
            files={"file": ("bn_q.jpg", img, "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        codes = {i["code"] for i in data["issues"]}
        assert "no_text" not in codes, f"Bengali handwriting flagged as no_text: {data}"
        assert data["has_text"] is True

    def test_blank_image_still_flags_no_text(self, session):
        """Regression: the ink-density heuristic must NOT swallow the blank case."""
        r = session.post(
            f"{API}/quality-check",
            files={"file": ("blank_q.jpg", _blank_image(), "image/jpeg")},
        )
        assert r.status_code == 200
        data = r.json()
        codes = {i["code"] for i in data["issues"]}
        assert "no_text" in codes, f"blank should flag no_text: {data}"
        assert data["has_text"] is False
