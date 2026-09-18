"""Ad-hoc single-shot test: with an INVALID EMERGENT_LLM_KEY the /api/extract
endpoint must still return 200 and set engine=='tesseract'. Run only after the
backend has been restarted with the invalid key; REVERT immediately after.
"""
import io
import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://docx-capture.preview.emergentagent.com"
).rstrip("/")


def _text_image() -> bytes:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not Path(font_path).exists():
        font_path = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    img = Image.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 64)
    d.text((40, 140), "Hello Tesseract Fallback", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def main():
    r = requests.post(
        f"{BASE_URL}/api/extract",
        files={"file": ("fallback.jpg", _text_image(), "image/jpeg")},
        timeout=90,
    )
    print("status:", r.status_code)
    print("body:", r.text[:500])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("engine") == "tesseract", f"Expected tesseract fallback, got {data}"
    assert "text" in data
    print("FALLBACK OK — engine=tesseract, text:", data["text"][:200])


if __name__ == "__main__":
    main()
