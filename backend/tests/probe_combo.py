"""Compare draft/refine engine combos on the real sample."""
import asyncio
import difflib
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, "/app/backend")
import server  # noqa: E402

TRUTH = Path("/app/backend/tests/fixtures/real_sample_truth.txt").read_text(encoding="utf-8")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("→", " ").replace("->", " ")
    s = re.sub(r"[।,.?!()\[\]\"'’‘“”*:;\-–—…]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def acc(ref: str, hyp: str):
    r, h = ref.split(), hyp.split()
    sm = difflib.SequenceMatcher(None, r, h)
    word = sum(b.size for b in sm.get_matching_blocks()) / max(1, len(r))
    rc, hc = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    smc = difflib.SequenceMatcher(None, rc, hc)
    char = sum(b.size for b in smc.get_matching_blocks()) / max(1, len(rc))
    return word * 100, char * 100


async def run(draft_engine: str, refine_engine: str, lines_per_band: int) -> None:
    img = Path("/tmp/sample.jpg").read_bytes()
    prepared = await asyncio.to_thread(server.prepare_vision_inputs, img, 2400, lines_per_band)
    ref = norm(TRUTH)

    t0 = time.time()
    parts = await asyncio.gather(
        *[
            server.vision_call(draft_engine, b, server.BAND_PROMPT, server.VISION_OCR_SYSTEM)
            for b in prepared["bands"]
        ]
    )
    draft = server._finalize_ocr_text("\n".join(p.strip() for p in parts if p.strip()))
    t_draft = time.time() - t0
    w, c = acc(ref, norm(draft))
    print(
        f"draft[{draft_engine}] bands={len(prepared['bands'])} lpb={lines_per_band} "
        f"{t_draft:.1f}s word={w:.1f}% char={c:.1f}%",
        flush=True,
    )

    t0 = time.time()
    refined = server._finalize_ocr_text(
        await server.vision_call(
            refine_engine,
            prepared["page"],
            f"Draft transcription to verify and correct:\n\n{draft}",
            server.REFINE_SYSTEM,
        )
    )
    w, c = acc(ref, norm(refined))
    print(f"refine[{refine_engine}] {time.time() - t0:.1f}s word={w:.1f}% char={c:.1f}%", flush=True)
    Path(f"/tmp/out_{draft_engine}_{refine_engine}_{lines_per_band}.txt").write_text(refined, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], int(sys.argv[3])))
