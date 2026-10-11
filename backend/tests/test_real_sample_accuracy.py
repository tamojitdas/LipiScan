"""Accuracy regression on the user's real handwriting photo.

The page is dense Bengali cursive (≈30 lines) photographed on a phone. Ground
truth was supplied by the user. We assert the hybrid pipeline (Flash drafts the
line bands, Pro proofreads the page) stays above the accuracy we measured when
it was built, so future prompt/pipeline changes cannot silently regress it.
"""
import difflib
import re
import unicodedata
from pathlib import Path

import requests
from extract_client import extract

API = "http://localhost:8001/api"
FIXTURES = Path(__file__).parent / "fixtures"
IMAGE = FIXTURES / "real_sample.jpg"
TRUTH = (FIXTURES / "real_sample_truth.txt").read_text(encoding="utf-8")

MIN_WORD_ACCURACY = 85.0
MIN_CHAR_ACCURACY = 90.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("→", " ").replace("->", " ")
    s = re.sub(r"[।,.?!()\[\]\"'’‘“”*:;\-–—…]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _word_accuracy(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    sm = difflib.SequenceMatcher(None, r, h)
    return 100 * sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def _char_accuracy(ref: str, hyp: str) -> float:
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    sm = difflib.SequenceMatcher(None, r, h)
    return 100 * sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def test_real_handwriting_sample_accuracy():
    data = extract(("real_sample.jpg", IMAGE.read_bytes(), "image/jpeg"), engine="gemini-pro")
    assert data["engine"] == "gemini-pro", data

    ref, hyp = _norm(TRUTH), _norm(data["text"])
    word = _word_accuracy(ref, hyp)
    char = _char_accuracy(ref, hyp)
    print(f"\nreal sample: word={word:.1f}% char={char:.1f}% chars={len(data['text'])}")
    assert word >= MIN_WORD_ACCURACY, f"word accuracy {word:.1f}% < {MIN_WORD_ACCURACY}%\n{data['text']}"
    assert char >= MIN_CHAR_ACCURACY, f"char accuracy {char:.1f}% < {MIN_CHAR_ACCURACY}%\n{data['text']}"
