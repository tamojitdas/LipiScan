"""Measure accuracy + wall-clock for all three engines on the real sample."""
import difflib, re, time, json, unicodedata
from pathlib import Path
import requests

API = "http://localhost:8001/api"
F = Path("/app/backend/tests/fixtures")
IMG = F / "real_sample.jpg"
TRUTH = (F / "real_sample_truth.txt").read_text(encoding="utf-8")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("→", " ").replace("->", " ")
    s = re.sub(r"[।,.?!()\[\]\"'’‘“”*:;\-–—…]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def word_acc(ref, hyp):
    r, h = ref.split(), hyp.split()
    sm = difflib.SequenceMatcher(None, r, h)
    return 100 * sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def char_acc(ref, hyp):
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    sm = difflib.SequenceMatcher(None, r, h)
    return 100 * sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def run(engine):
    t = time.time()
    with IMG.open("rb") as f:
        r = requests.post(
            f"{API}/extract",
            files={"file": ("real_sample.jpg", f, "image/jpeg")},
            data={"engine": engine},
            timeout=400,
        )
    dt = time.time() - t
    j = r.json()
    hyp = norm(j.get("text", ""))
    ref = norm(TRUTH)
    return {
        "engine_requested": engine,
        "engine_echoed": j.get("engine"),
        "status": r.status_code,
        "wall_clock_s": round(dt, 2),
        "chars": len(j.get("text", "")),
        "word_acc": round(word_acc(ref, hyp), 2),
        "char_acc": round(char_acc(ref, hyp), 2),
    }


results = {}
for e in ["gemini-pro", "gemini-flash", "gemma"]:
    try:
        results[e] = run(e)
        print(e, results[e])
    except Exception as ex:
        results[e] = {"error": str(ex)}
        print(e, "ERROR", ex)

Path("/app/test_reports/pytest/iter7_accuracy.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print("\n== saved to /app/test_reports/pytest/iter7_accuracy.json ==")
