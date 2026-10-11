"""Destructive fallback-chain verification for /api/extract.

Mutates /app/backend/.env to:
  1. Break HF_TOKEN only  -> expect engine == 'gemini' for engine=gemma or auto.
  2. Break BOTH HF_TOKEN + EMERGENT_LLM_KEY -> expect engine == 'tesseract'.

Restores the original .env + restarts the backend afterwards and verifies gemma works again.

Run manually (NOT in default pytest run):
    python /app/backend/tests/test_fallback_chain.py
"""
import io
import os
import shutil
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from extract_client import extract

ENV = Path("/app/backend/.env")
BACKUP = Path("/app/backend/.env.bak_fallback_test")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://docx-capture.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def restart_backend():
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=False, capture_output=True)
    # wait for backend to accept requests
    for _ in range(60):
        try:
            r = requests.get(f"{API}/", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("backend did not come back up")


def _rewrite_env(mutations: dict):
    """Rewrite .env preserving unspecified keys."""
    lines = ENV.read_text().splitlines()
    out = []
    seen = set()
    for ln in lines:
        if "=" in ln and not ln.lstrip().startswith("#"):
            k = ln.split("=", 1)[0].strip()
            if k in mutations:
                out.append(f"{k}={mutations[k]}")
                seen.add(k)
                continue
        out.append(ln)
    for k, v in mutations.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV.write_text("\n".join(out) + "\n")


def _render_image() -> bytes:
    candidates = [
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    font_path = next((p for p in candidates if Path(p).exists()), None)
    assert font_path, "no suitable font found"
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 60)
    d.text((40, 100), "Hello Fallback Test", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _extract(engine: str = "gemma") -> dict:
    return extract(("t.jpg", _render_image(), "image/jpeg"), engine=engine)


def main() -> int:
    assert ENV.exists(), "backend/.env missing"
    shutil.copy(ENV, BACKUP)
    try:
        # ---------- step 1: break HF_TOKEN only ----------
        print("\n[1] Breaking HF_TOKEN only — expect gemini fallback …")
        _rewrite_env({"HF_TOKEN": "hf_invalid_token_for_test_only"})
        restart_backend()
        data = _extract(engine="gemma")
        print("   -> engine:", data["engine"], "text:", repr(data["text"][:80]))
        assert data["engine"] == "gemini", f"expected gemini, got {data['engine']}"

        # ---------- step 2: break both HF_TOKEN AND EMERGENT_LLM_KEY ----------
        print("\n[2] Breaking HF_TOKEN AND EMERGENT_LLM_KEY — expect tesseract …")
        _rewrite_env({"HF_TOKEN": "hf_invalid", "EMERGENT_LLM_KEY": "sk-invalid-for-test"})
        restart_backend()
        data = _extract(engine="gemma")
        print("   -> engine:", data["engine"], "text:", repr(data["text"][:80]))
        assert data["engine"] == "tesseract", f"expected tesseract, got {data['engine']}"

        print("\n[3] Restoring .env and verifying gemma works again …")
    finally:
        shutil.copy(BACKUP, ENV)
        BACKUP.unlink()
        restart_backend()

    # Post-restore sanity: engine=gemma should return 'gemma' again
    data = _extract(engine="gemma")
    print("   -> engine:", data["engine"], "text:", repr(data["text"][:80]))
    assert data["engine"] == "gemma", f"after restore expected gemma, got {data['engine']}"
    print("\nALL FALLBACK ASSERTIONS PASSED — .env restored, gemma healthy again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
