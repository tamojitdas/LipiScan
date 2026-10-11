"""Direct pipeline probe (no HTTP): band count, per-stage timing, accuracy."""
import asyncio
import difflib
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, "/app/backend")

import server  # noqa: E402

IMAGE = Path("/tmp/sample.jpg")
TRUTH = (Path("/app/backend/tests/fixtures/real_sample_truth.txt")).read_text(encoding="utf-8")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("→", " ").replace("->", " ")
    s = re.sub(r"[।,.?!()\[\]\"'’‘“”*:;\-–—…]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def word_acc(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    sm = difflib.SequenceMatcher(None, r, h)
    return sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


def char_acc(ref: str, hyp: str) -> float:
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    sm = difflib.SequenceMatcher(None, r, h)
    return sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))


async def main() -> None:
    img_bytes = IMAGE.read_bytes()
    t0 = time.time()
    prepared = await asyncio.to_thread(server.prepare_vision_inputs, img_bytes)
    print(f"prep {time.time() - t0:.1f}s bands={len(prepared['bands'])}")

    engine = sys.argv[1] if len(sys.argv) > 1 else "gemini-pro"

    t0 = time.time()
    parts = await asyncio.gather(
        *[
            server.vision_call(engine, b, server.BAND_PROMPT, server.VISION_OCR_SYSTEM)
            for b in prepared["bands"]
        ]
    )
    draft = server._finalize_ocr_text("\n".join(p.strip() for p in parts if p.strip()))
    t_bands = time.time() - t0
    print(f"bands {t_bands:.1f}s draft_chars={len(draft)}")

    t0 = time.time()
    refined = server._finalize_ocr_text(
        await server.vision_call(
            engine,
            prepared["page"],
            f"Draft transcription to verify and correct:\n\n{draft}",
            server.REFINE_SYSTEM,
        )
    )
    print(f"refine {time.time() - t0:.1f}s refined_chars={len(refined)}")

    ref = norm(TRUTH)
    for label, text in (("draft", draft), ("refined", refined)):
        h = norm(text)
        print(f"{label}: word_acc={word_acc(ref, h) * 100:.1f}% char_acc={char_acc(ref, h) * 100:.1f}%")

    Path("/tmp/draft.txt").write_text(draft, encoding="utf-8")
    Path("/tmp/refined.txt").write_text(refined, encoding="utf-8")

    print("\n--- diffs vs truth (refined) ---")
    sm = difflib.SequenceMatcher(None, ref.split(), norm(refined).split())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            print(f"{tag}: {' '.join(ref.split()[i1:i2])!r} -> {' '.join(norm(refined).split()[j1:j2])!r}")


asyncio.run(main())
