"""Iteration 8: verify the async extract flow through the PUBLIC ingress.

CRITICAL regression check: POST /api/extract must return 202 immediately,
and the job must complete successfully (no 60s ingress 502) through the
public URL. Also validates edge cases on the job endpoints.
"""
import difflib
import os
import re
import time
import unicodedata
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://docx-capture.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

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
    r = list(ref.replace(" ", ""))
    h = list(hyp.replace(" ", ""))
    sm = difflib.SequenceMatcher(None, r, h)
    return 100 * sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def _poll(job_id: str, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        res = requests.get(f"{API}/extract/{job_id}", timeout=30)
        assert res.status_code == 200, f"poll failed: {res.status_code} {res.text}"
        last = res.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(2)
    raise AssertionError(f"timed out: {last}")


# ---------- async transport ----------
def test_post_returns_202_immediately():
    t0 = time.time()
    with IMAGE.open("rb") as fh:
        res = requests.post(
            f"{API}/extract",
            files={"file": ("real_sample.jpg", fh, "image/jpeg")},
            data={"engine": "gemini-pro"},
            timeout=30,
        )
    elapsed = time.time() - t0
    assert res.status_code == 202, f"{res.status_code} {res.text}"
    body = res.json()
    assert body["status"] == "processing"
    assert "job_id" in body and len(body["job_id"]) == 24
    # Should be fast — just validation + insert, well below 60s ingress limit
    assert elapsed < 15, f"POST took {elapsed:.1f}s (should be instant)"


def test_real_sample_through_public_url_gemini_pro():
    """The whole point of iter 8: no 502, accuracy still meets the floor."""
    t0 = time.time()
    with IMAGE.open("rb") as fh:
        res = requests.post(
            f"{API}/extract",
            files={"file": ("real_sample.jpg", fh, "image/jpeg")},
            data={"engine": "gemini-pro"},
            timeout=30,
        )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]
    job = _poll(job_id, timeout=300)
    elapsed = time.time() - t0

    assert job["status"] == "done", job
    assert job["engine"] == "gemini-pro", job
    assert job.get("text")

    ref = _norm(TRUTH)
    hyp = _norm(job["text"])
    word = _word_accuracy(ref, hyp)
    char = _char_accuracy(ref, hyp)
    print(
        f"\n[public gemini-pro] wall={elapsed:.1f}s word={word:.2f}% char={char:.2f}% chars={len(job['text'])}"
    )
    assert word >= MIN_WORD_ACCURACY, f"word {word:.2f}% < {MIN_WORD_ACCURACY}%"
    assert char >= MIN_CHAR_ACCURACY, f"char {char:.2f}% < {MIN_CHAR_ACCURACY}%"


# ---------- edge cases ----------
def test_get_malformed_job_id_returns_400():
    res = requests.get(f"{API}/extract/not-an-oid", timeout=10)
    assert res.status_code == 400


def test_get_unknown_but_valid_job_id_returns_404():
    res = requests.get(f"{API}/extract/507f1f77bcf86cd799439011", timeout=10)
    assert res.status_code == 404


def test_post_empty_file_returns_400():
    res = requests.post(
        f"{API}/extract",
        files={"file": ("empty.jpg", b"", "image/jpeg")},
        data={"engine": "gemini-pro"},
        timeout=15,
    )
    assert res.status_code == 400


def test_post_non_image_bytes_returns_400():
    """Validated synchronously before the job is created — no 'processing' row left."""
    res = requests.post(
        f"{API}/extract",
        files={"file": ("junk.jpg", b"this is not an image at all", "image/jpeg")},
        data={"engine": "gemini-pro"},
        timeout=15,
    )
    assert res.status_code == 400


# ---------- fallback inside a job ----------
def test_gemma_job_finishes_done_never_stuck():
    """Engine=gemma: must end with status=done; engine may be gemma or a fallback id."""
    with IMAGE.open("rb") as fh:
        res = requests.post(
            f"{API}/extract",
            files={"file": ("real_sample.jpg", fh, "image/jpeg")},
            data={"engine": "gemma"},
            timeout=30,
        )
    assert res.status_code == 202, res.text
    job = _poll(res.json()["job_id"], timeout=360)
    assert job["status"] == "done", job
    assert job["engine"] in ("gemma", "gemini-pro", "gemini-flash", "tesseract"), job
    assert isinstance(job.get("text"), str)
