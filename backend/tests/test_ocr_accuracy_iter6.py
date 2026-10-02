"""Iteration-6 OCR accuracy tests.

Generates several deterministic test pages whose ground-truth text we know, posts
them to /api/extract (engine=gemini-pro, the new default), and measures
word-level accuracy per case + latency. Cases:
  1) Multi-line Bengali (Lohit-Bengali, 6 lines).
  2) Mixed Bengali + English (Bengali rendered with Lohit-Bengali, English with
     FreeSerifItalic -- Lohit has no Latin glyphs).
  3) Degraded page (2.5 degrees skew + mild blur + Gaussian noise + JPEG q80).
  4) Short 2-line page (should take the single full-page branch, no banding).

Also probes the 10+-line pipeline for drops/duplication.
"""
import io
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://docx-capture.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

BN_FONT = "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf"
EN_FONT = "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf"


def _wrap_lines(text: str) -> list:
    return [ln for ln in text.split("\n") if ln.strip()]


def _render_mixed(lines, size=(1600, 1200)) -> Image.Image:
    """Render each line with the font appropriate for its script.
    Bengali chars (U+0980-U+09FF) force the Bengali font; otherwise English.
    """
    img = Image.new("RGB", size, (252, 250, 246))
    d = ImageDraw.Draw(img)
    bn = ImageFont.truetype(BN_FONT, 56)
    en = ImageFont.truetype(EN_FONT, 56)
    y = 70
    for ln in lines:
        has_bn = any("\u0980" <= c <= "\u09FF" for c in ln)
        has_en = any(c.isascii() and c.isalpha() for c in ln)
        if has_bn and has_en:
            # draw segment by segment
            x = 60
            seg = ""
            seg_is_bn = None
            for c in ln:
                c_is_bn = "\u0980" <= c <= "\u09FF"
                if seg_is_bn is None:
                    seg_is_bn = c_is_bn
                if c_is_bn != seg_is_bn and seg:
                    f = bn if seg_is_bn else en
                    d.text((x, y), seg, fill=(18, 18, 28), font=f)
                    x += int(d.textlength(seg, font=f))
                    seg = ""
                    seg_is_bn = c_is_bn
                seg += c
            if seg:
                f = bn if seg_is_bn else en
                d.text((x, y), seg, fill=(18, 18, 28), font=f)
        else:
            f = bn if has_bn else en
            d.text((60, y), ln, fill=(18, 18, 28), font=f)
        y += 90
    return img


def _to_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _degrade(jpeg: bytes, angle: float = 2.5) -> bytes:
    """Introduce 2.5 degrees skew + slight blur + noise + JPEG q80."""
    arr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    arr = cv2.warpAffine(arr, m, (w, h), borderValue=(252, 250, 246))
    arr = cv2.GaussianBlur(arr, (3, 3), 0)
    noise = np.random.default_rng(42).normal(0, 6, arr.shape).astype(np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    assert ok
    return buf.tobytes()


# --- Ground truth fixtures ---
BN_LINES = [
    "আমার সোনার বাংলা",
    "আমি তোমায় ভালোবাসি",
    "চিরদিন তোমার আকাশ",
    "তোমার বাতাস",
    "আমার প্রাণে বাজায়",
    "মধুর বাঁশি",
]

MIXED_LINES = [
    "আজ Monday, class শুরু",
    "Math আর Science পড়তে হবে",
    "আমার roll number 42",
    "Teacher বললেন homework করো",
    "Exam আসছে next week",
]

SHORT_LINES = [
    "Hello world",
    "LipiScan test",
]

LONG_LINES = [
    "Line one of the long test",
    "Line two should be here",
    "This is the third line",
    "Fourth line of the page",
    "Fifth line continues here",
    "Line six of handwritten text",
    "Seventh row of the note",
    "Eighth line keeps going",
    "Ninth line almost there",
    "Tenth line of the page",
    "Eleventh line finishes it",
    "Twelfth and final line",
]


def _bn_simplify(s: str) -> str:
    """Collapse whitespace and strip punctuation for fair comparison."""
    s = re.sub(r"[।,.;:!?()\[\]\"'`\-—–]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _word_accuracy(predicted: str, truth: str) -> float:
    """Overlap-based word accuracy (counts correct words from truth that appear
    anywhere in prediction, divided by truth length). Case-insensitive."""
    tw = _bn_simplify(truth).lower().split()
    pw = _bn_simplify(predicted).lower().split()
    if not tw:
        return 0.0
    pset = {}
    for w in pw:
        pset[w] = pset.get(w, 0) + 1
    hit = 0
    for w in tw:
        if pset.get(w, 0) > 0:
            hit += 1
            pset[w] -= 1
    return hit / len(tw)


def _post_extract(jpeg: bytes, name: str, engine: str = "gemini-pro"):
    t0 = time.monotonic()
    r = requests.post(
        f"{API}/extract",
        data={"engine": engine},
        files={"file": (name, jpeg, "image/jpeg")},
        timeout=180,
    )
    dt = time.monotonic() - t0
    return r, dt


ACCURACY_FLOOR = 0.85
LATENCY_WARN = 90.0


@pytest.fixture(scope="module")
def report():
    out = {"cases": []}
    yield out
    # Dump summary at the end to the test report folder.
    Path("/app/test_reports/pytest").mkdir(parents=True, exist_ok=True)
    with open("/app/test_reports/pytest/iter6_accuracy.json", "w") as f:
        import json
        json.dump(out, f, indent=2, ensure_ascii=False)


class TestAccuracyIteration6:
    def test_bengali_multiline(self, report):
        truth = "\n".join(BN_LINES)
        img = _to_jpeg(_render_mixed(BN_LINES))
        r, dt = _post_extract(img, "bn_multi.jpg")
        assert r.status_code == 200, r.text
        data = r.json()
        acc = _word_accuracy(data["text"], truth)
        report["cases"].append({
            "case": "bengali_multiline", "engine": data["engine"], "latency_s": round(dt, 2),
            "accuracy": round(acc, 3), "truth": truth, "predicted": data["text"],
        })
        assert data["engine"] in {"gemini-pro", "gemini-flash", "gemma", "tesseract"}
        assert acc >= ACCURACY_FLOOR, f"BN word accuracy {acc:.2%} below floor; got {data['text']!r}"
        assert dt < LATENCY_WARN, f"latency {dt:.1f}s exceeded warn threshold"

    def test_mixed_bengali_english(self, report):
        truth = "\n".join(MIXED_LINES)
        img = _to_jpeg(_render_mixed(MIXED_LINES))
        r, dt = _post_extract(img, "mixed.jpg")
        assert r.status_code == 200, r.text
        data = r.json()
        acc = _word_accuracy(data["text"], truth)
        report["cases"].append({
            "case": "mixed_bengali_english", "engine": data["engine"], "latency_s": round(dt, 2),
            "accuracy": round(acc, 3), "truth": truth, "predicted": data["text"],
        })
        # Must contain at least some Bengali and some English
        assert any("\u0980" <= c <= "\u09FF" for c in data["text"]), f"BN missing: {data['text']!r}"
        assert any(c.isascii() and c.isalpha() for c in data["text"]), f"EN missing: {data['text']!r}"
        assert acc >= ACCURACY_FLOOR, f"Mixed word accuracy {acc:.2%} below floor; got {data['text']!r}"
        assert dt < LATENCY_WARN

    def test_degraded_page(self, report):
        truth = "\n".join(MIXED_LINES)
        clean = _to_jpeg(_render_mixed(MIXED_LINES))
        degraded = _degrade(clean, angle=2.5)
        r, dt = _post_extract(degraded, "degraded.jpg")
        assert r.status_code == 200, r.text
        data = r.json()
        acc = _word_accuracy(data["text"], truth)
        report["cases"].append({
            "case": "degraded_page", "engine": data["engine"], "latency_s": round(dt, 2),
            "accuracy": round(acc, 3), "truth": truth, "predicted": data["text"],
        })
        assert acc >= ACCURACY_FLOOR, f"Degraded word accuracy {acc:.2%} below floor; got {data['text']!r}"
        assert dt < LATENCY_WARN

    def test_short_two_lines(self, report):
        truth = "\n".join(SHORT_LINES)
        img = _to_jpeg(_render_mixed(SHORT_LINES, size=(1200, 400)))
        r, dt = _post_extract(img, "short.jpg")
        assert r.status_code == 200, r.text
        data = r.json()
        acc = _word_accuracy(data["text"], truth)
        report["cases"].append({
            "case": "short_two_lines", "engine": data["engine"], "latency_s": round(dt, 2),
            "accuracy": round(acc, 3), "truth": truth, "predicted": data["text"],
        })
        assert acc >= ACCURACY_FLOOR, f"Short word accuracy {acc:.2%} below floor; got {data['text']!r}"
        assert dt < LATENCY_WARN

    def test_long_page_no_drops_no_dupes(self, report):
        truth = "\n".join(LONG_LINES)
        img = _to_jpeg(_render_mixed(LONG_LINES, size=(1600, 1600)))
        r, dt = _post_extract(img, "long.jpg")
        assert r.status_code == 200, r.text
        data = r.json()
        acc = _word_accuracy(data["text"], truth)
        # Count distinct "Line N" tokens from truth preserved in prediction
        tokens = ["one", "two", "third", "fourth", "fifth", "six", "seventh",
                  "eighth", "ninth", "tenth", "eleventh", "twelfth"]
        low = data["text"].lower()
        found = [t for t in tokens if t in low]
        # look for duplicates: no line should appear more than twice
        pred_lines = [ln.strip().lower() for ln in data["text"].splitlines() if ln.strip()]
        dupes = {ln for ln in pred_lines if pred_lines.count(ln) > 2}
        report["cases"].append({
            "case": "long_page_12_lines", "engine": data["engine"], "latency_s": round(dt, 2),
            "accuracy": round(acc, 3), "found_tokens": found, "dupes": sorted(dupes),
            "truth": truth, "predicted": data["text"],
        })
        assert len(found) >= 10, f"Dropped lines: only {len(found)}/12 ordinal tokens present: {data['text']!r}"
        assert not dupes, f"Lines duplicated more than twice: {dupes}"
        assert dt < LATENCY_WARN
