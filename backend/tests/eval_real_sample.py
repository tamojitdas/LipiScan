"""Accuracy harness for the user's real handwriting sample.

Usage:
    python tests/eval_real_sample.py [engine]

Prints character error rate (CER), word accuracy and a side-by-side diff of the
lines so prompt/pipeline tweaks can be compared objectively.
"""
import difflib
import re
import sys
import time
from pathlib import Path

import requests
from extract_client import extract

API = "http://localhost:8001/api"
HERE = Path(__file__).parent
IMAGE = Path("/tmp/sample.jpg")
TRUTH = (HERE / "fixtures" / "real_sample_truth.txt").read_text(encoding="utf-8")


def norm(s: str) -> str:
    s = s.replace("→", " ").replace("->", " ")
    s = re.sub(r"[।,.?!()\[\]\"'’‘“”*:;\-–—]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cer(ref: str, hyp: str) -> float:
    ref_c, hyp_c = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    sm = difflib.SequenceMatcher(None, ref_c, hyp_c)
    return 1 - sm.ratio()


def word_acc(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    sm = difflib.SequenceMatcher(None, r, h)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / max(1, len(r))


def main() -> None:
    engine = sys.argv[1] if len(sys.argv) > 1 else "gemini-pro"
    started = time.time()
    data = extract(("sample.jpg", IMAGE.read_bytes(), "image/jpeg"), engine=engine)
    took = time.time() - started

    ref, hyp = norm(TRUTH), norm(data["text"])
    print(f"engine={data['engine']} time={took:.1f}s chars={len(data['text'])}")
    print(f"CER={cer(ref, hyp) * 100:.1f}%  word_acc={word_acc(ref, hyp) * 100:.1f}%")
    print("\n--- extracted ---\n")
    print(data["text"])

    print("\n--- missing / wrong words (ref -> hyp) ---")
    sm = difflib.SequenceMatcher(None, ref.split(), hyp.split())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            print(f"{tag}: {' '.join(ref.split()[i1:i2])!r} -> {' '.join(hyp.split()[j1:j2])!r}")


if __name__ == "__main__":
    main()
