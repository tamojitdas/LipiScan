"""Iteration-4 engine selection & fallback tests.

Verifies the new /api/extract engine form field:
- engine omitted -> defaults to Gemma first (engine is 'gemma' or 'gemini' on fallback).
- engine='gemma' -> returns 'gemma' when HF is healthy.
- engine='gemini' -> returns 'gemini' when EMERGENT_LLM_KEY works.
- Invalid/empty image still returns 400 regardless of engine.
- Fallback chain (destructive sub-tests live separately in test_fallback_chain.py because they
  need to mutate /app/backend/.env and restart the backend).
"""
import io
import os
from pathlib import Path

import pytest
import requests
from PIL import Image, ImageDraw, ImageFont
from extract_client import extract, start_extract

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://docx-capture.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _find_font(candidates):
    for p in candidates:
        if Path(p).exists():
            return p
    return None


EN_FONTS = [
    "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BN_FONTS = [
    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifBengali-Bold.ttf",
]


def _render(text: str, font_path: str, font_size: int = 64) -> bytes:
    img = Image.new("RGB", (1000, 500), (250, 248, 244))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    y = 60
    for ln in text.split("\n"):
        d.text((60, y), ln, fill=(20, 20, 30), font=font)
        y += int(font_size * 1.4)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _en_image() -> bytes:
    fp = _find_font(EN_FONTS)
    assert fp, "no font available"
    return _render("The quick brown fox\njumps over the lazy dog", fp, 70)


def _bn_image() -> bytes:
    fp = _find_font(BN_FONTS)
    assert fp, "no Bengali font installed"
    return _render("আমার সোনার বাংলা\nআমি তোমায় ভালোবাসি", fp, 60)


@pytest.fixture(scope="module")
def session():
    return requests.Session()


class TestEngineSelection:
    """engine form field + fallback chain tolerance."""

    def test_engine_omitted_defaults_to_gemma_first(self, session):
        data = extract(("en.jpg", _en_image(), "image/jpeg"))
        assert data["engine"] in {"gemini-pro", "gemini-flash", "gemma"}, data
        # If HF is up, 'auto' should prefer gemma. Accept gemini as graceful fallback.
        assert "id" in data and isinstance(data["text"], str)

    def test_engine_gemma_explicit_english(self, session):
        data = extract(("en.jpg", _en_image(), "image/jpeg"), engine="gemma")
        # Must be in {gemma, gemini} (gemini only if Gemma failed and fell back)
        assert data["engine"] in {"gemini-pro", "gemini-flash", "gemma", "tesseract"}, data
        # Prefer gemma when HF_TOKEN is set in .env
        assert data["engine"] == "gemma", f"expected gemma, got {data['engine']} (text={data['text']!r})"
        low = data["text"].lower()
        hits = sum(1 for w in ["quick", "brown", "fox", "lazy", "dog"] if w in low)
        assert hits >= 3, f"too few keywords: {data['text']!r}"

    def test_engine_gemma_explicit_bengali(self, session):
        data = extract(("bn.jpg", _bn_image(), "image/jpeg"), engine="gemma")
        assert data["engine"] == "gemma", f"expected gemma, got {data}"
        txt = data["text"]
        assert any("\u0980" <= c <= "\u09FF" for c in txt), f"Bengali missing: {txt!r}"

    def test_engine_gemini_explicit(self, session):
        data = extract(("en.jpg", _en_image(), "image/jpeg"), engine="gemini-flash")
        assert data["engine"] == "gemini-flash", f"expected gemini, got {data}"
        low = data["text"].lower()
        hits = sum(1 for w in ["quick", "brown", "fox", "lazy", "dog"] if w in low)
        assert hits >= 3, f"too few keywords: {data['text']!r}"

    def test_extract_empty_file_returns_400(self, session):
        r = start_extract(("empty.jpg", b"", "image/jpeg"), engine="gemma")
        assert r.status_code == 400

    def test_extract_invalid_image_returns_400(self, session):
        r = start_extract(("bad.jpg", b"not an image at all, just text bytes", "image/jpeg"), engine="gemma")
        assert r.status_code == 400
