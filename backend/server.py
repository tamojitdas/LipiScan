import asyncio
import base64
import io
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional

import cv2
import httpx
import numpy as np
import pytesseract
from docx import Document as DocxDocument
from dotenv import load_dotenv
from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI()
api_router = APIRouter(prefix="/api")

DOWNLOADS_DIR = Path("/tmp/lipiscan_downloads")
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def ensure_tesseract():
    """Self-heal: fresh containers may miss the tesseract system package."""
    if shutil.which("tesseract"):
        return
    logging.warning("tesseract not found; installing tesseract-ocr (ben+eng)...")
    try:
        subprocess.run(["apt-get", "update", "-qq"], check=False, capture_output=True, timeout=300)
        subprocess.run(
            ["apt-get", "install", "-y", "-qq", "tesseract-ocr", "tesseract-ocr-ben", "tesseract-ocr-eng"],
            check=True,
            capture_output=True,
            timeout=300,
        )
        logging.info("tesseract installed successfully")
    except Exception:
        logging.exception("automatic tesseract install failed; OCR endpoints will error")


@app.on_event("startup")
async def startup_checks():
    await asyncio.to_thread(ensure_tesseract)


# ---------- Mongo helpers ----------
PyObjectId = Annotated[str, BeforeValidator(str)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, doc: dict):
        return cls.model_validate(doc)


class HistoryItem(BaseDocument):
    text: str
    snippet: str
    char_count: int
    created_at: datetime
    deleted_at: Optional[datetime] = None


# ---------- Image analysis ----------
def _decode_gray(img_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Could not decode image")
    return img


def _resize_max(img: np.ndarray, max_dim: int) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_dim:
        return img
    scale = max_dim / m
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _clean_text(raw: str) -> str:
    lines = [ln.rstrip() for ln in raw.splitlines()]
    out: List[str] = []
    blank = False
    for ln in lines:
        if ln.strip():
            out.append(ln.strip())
            blank = False
        else:
            if not blank and out:
                out.append("")
            blank = True
    text = "\n".join(out).strip()
    return re.sub(r"[ \t]{2,}", " ", text)


def _has_ink_marks(gray: np.ndarray) -> bool:
    """Handwriting-friendly text presence check: look for dark ink strokes.

    Tesseract often reads nothing on handwriting, so we also measure the share of
    dark pixels after adaptive thresholding — writing covers a small but non-zero
    part of the page, while blank/uniform frames cover almost none.
    """
    small = _resize_max(gray, 900)
    binary = cv2.adaptiveThreshold(
        small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 12
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    ink_ratio = float(binary.mean()) / 255.0
    return 0.004 <= ink_ratio <= 0.45


def analyze_quality_sync(img_bytes: bytes) -> dict:
    gray = _decode_gray(img_bytes)
    gray = _resize_max(gray, 1200)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    small = _resize_max(gray, 900)
    quick = pytesseract.image_to_string(small, lang="ben+eng", config="--psm 6")
    readable = len([c for c in quick if not c.isspace()])
    has_text = readable >= 3 or _has_ink_marks(gray)

    issues = []
    if blur_score < 45:
        issues.append({"code": "blur", "label": "Sharpness", "message": "Image is too blurry. Hold the phone steady and retake."})
    if brightness < 55:
        issues.append({"code": "dim", "label": "Lighting", "message": "Lighting is too dim. Move to brighter light."})
    if not has_text:
        issues.append({"code": "no_text", "label": "Text", "message": "No readable text detected in this frame."})

    return {
        "ok": len(issues) == 0,
        "blur_score": round(blur_score, 1),
        "brightness": round(brightness, 1),
        "has_text": has_text,
        "issues": issues,
    }


def run_ocr_sync(img_bytes: bytes) -> str:
    gray = _decode_gray(img_bytes)
    gray = _resize_max(gray, 1600)
    raw = pytesseract.image_to_string(gray, lang="ben+eng", config="--psm 6")
    return _clean_text(raw)


def prepare_for_vision_sync(img_bytes: bytes) -> str:
    """Downscale + re-encode as JPEG, returned base64 for the vision model."""
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    img = _resize_max(img, 1600)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("Could not encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


VISION_OCR_SYSTEM = (
    "You are an expert handwriting transcription engine for Bengali (Bangla) and English. "
    "You are given a photo of handwritten (or printed) notes. Transcribe every word you can read, "
    "in reading order, keeping the original language of each part (Bengali stays Bengali, English "
    "stays English). Fix obvious handwriting/spelling slips, add sensible punctuation and keep the "
    "line/paragraph structure of the page. Never translate, never summarise, never add commentary, "
    "headings or explanations that are not on the page. If a word is truly illegible write it as [?]. "
    "If the image contains no readable text at all, reply with exactly: NO_TEXT_FOUND. "
    "Reply with ONLY the transcribed text."
)

HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
HF_OCR_MODEL = os.environ.get("HF_OCR_MODEL", "google/gemma-4-31B-it")


def _finalize_ocr_text(text: str) -> str:
    text = text.strip()
    if text.upper().startswith("NO_TEXT_FOUND"):
        return ""
    return _clean_text(text)


async def run_gemma_ocr(img_bytes: bytes) -> str:
    """Gemma 4 (open model) vision OCR via Hugging Face Inference Providers."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise RuntimeError("HF_TOKEN is not configured")
    image_b64 = await asyncio.to_thread(prepare_for_vision_sync, img_bytes)
    payload = {
        "model": HF_OCR_MODEL,
        "messages": [
            {"role": "system", "content": VISION_OCR_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe the handwritten text in this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        "temperature": 0,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as http:
        res = await http.post(
            HF_ROUTER_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Hugging Face request failed ({res.status_code}): {res.text[:200]}")
    body = res.json()
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Unexpected Hugging Face response")
    if isinstance(text, list):  # some providers return content parts
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return _finalize_ocr_text(str(text))


async def run_vision_ocr(img_bytes: bytes) -> str:
    """Gemini 3 Flash vision OCR. Raises on failure so another engine can take over."""
    image_b64 = await asyncio.to_thread(prepare_for_vision_sync, img_bytes)
    chat = LlmChat(
        api_key=os.environ.get("EMERGENT_LLM_KEY", ""),
        session_id=f"ocr-{uuid.uuid4().hex}",
        system_message=VISION_OCR_SYSTEM,
    ).with_model("gemini", "gemini-3-flash-preview")
    result = await chat.send_message(
        UserMessage(
            text="Transcribe the handwritten text in this image.",
            file_contents=[ImageContent(image_base64=image_b64)],
        )
    )
    return _finalize_ocr_text(str(result))


# ---------- Routes ----------
@api_router.get("/")
async def root():
    return {"message": "LipiScan API"}


@api_router.post("/quality-check")
async def quality_check(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        result = await asyncio.to_thread(analyze_quality_sync, data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image")
    return result


@api_router.post("/extract")
async def extract_text(file: UploadFile = File(...), engine: str = Form("auto")):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    # Engine preference: "auto"/"gemma" -> Gemma 4, then Gemini, then offline Tesseract.
    # "gemini" -> Gemini first. Tesseract is always the last resort.
    order = ["gemini", "gemma"] if engine == "gemini" else ["gemma", "gemini"]
    runners = {"gemma": run_gemma_ocr, "gemini": run_vision_ocr}

    text = ""
    used = ""
    errors: List[str] = []
    for name in order:
        try:
            text = await runners[name](data)
            used = name
            break
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid image")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logging.warning("%s OCR failed: %s", name, exc)

    if not used:
        logging.error("all vision engines failed: %s", " | ".join(errors))
        try:
            text = await asyncio.to_thread(run_ocr_sync, data)
            used = "tesseract"
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid image")

    item = HistoryItem(
        text=text,
        snippet=text[:140],
        char_count=len(text),
        created_at=datetime.now(timezone.utc),
    )
    res = await db.history.insert_one(item.to_mongo())
    return {"id": str(res.inserted_id), "text": text, "engine": used}


@api_router.get("/history")
async def get_history():
    docs = await db.history.find({"deleted_at": None}).sort("created_at", -1).to_list(100)
    return [HistoryItem.from_mongo(d).model_dump() for d in docs]


@api_router.delete("/history/{item_id}")
async def delete_history(item_id: str):
    from bson import ObjectId

    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    res = await db.history.update_one({"_id": oid}, {"$set": {"deleted_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


CLEANUP_SYSTEM = (
    "You are an OCR post-processing assistant specializing in Bengali and English handwriting. "
    "The user sends raw OCR output that may contain recognition errors, broken words, wrong "
    "characters, bad spacing and stray symbols. Rewrite it as clean, correctly spelled, properly "
    "punctuated text with sensible sentence and paragraph structure. Keep the original language(s) "
    "of each part (Bengali stays Bengali, English stays English). Preserve the meaning; never add "
    "new information or commentary. Reply with ONLY the corrected text, nothing else."
)


class CleanupRequest(BaseModel):
    text: str


@api_router.post("/cleanup")
async def cleanup_text(body: CleanupRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="No text to clean up")
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"cleanup-{uuid.uuid4().hex}",
        system_message=CLEANUP_SYSTEM,
    ).with_model("openai", "gpt-5.4")
    try:
        result = await chat.send_message(UserMessage(text=body.text))
    except Exception:
        logging.exception("cleanup failed")
        raise HTTPException(status_code=502, detail="AI cleanup failed. Please try again.")
    cleaned = str(result).strip()
    if not cleaned:
        raise HTTPException(status_code=502, detail="AI returned an empty response")
    return {"text": cleaned}


def append_docx_sync(docx_bytes: bytes, text: str, position: str, heading: str) -> bytes:
    doc = DocxDocument(io.BytesIO(docx_bytes))
    paragraphs = [p for p in text.split("\n") if p.strip()]
    if not paragraphs:
        raise HTTPException(status_code=400, detail="No text to append")

    if position == "after_heading":
        target = None
        needle = heading.strip().lower()
        for p in doc.paragraphs:
            if needle and needle in p.text.strip().lower():
                target = p
                break
        if target is None:
            raise HTTPException(status_code=404, detail=f'Heading "{heading}" not found in document')
        anchor = target._p
        for t in paragraphs:
            new_p = doc.add_paragraph(t)
            anchor.addnext(new_p._p)
            anchor = new_p._p
    else:
        for t in paragraphs:
            doc.add_paragraph(t)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


@api_router.post("/append-docx")
async def append_docx(
    file: UploadFile = File(...),
    text: str = Form(...),
    position: str = Form("end"),
    heading: str = Form(""),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        result_bytes = await asyncio.to_thread(append_docx_sync, data, text, position, heading)
    except HTTPException:
        raise
    except Exception:
        logging.exception("docx append failed")
        raise HTTPException(status_code=400, detail="Could not open this file. Make sure it is a valid .docx document.")

    download_id = uuid.uuid4().hex
    out_path = DOWNLOADS_DIR / f"{download_id}.docx"
    out_path.write_bytes(result_bytes)
    base = (file.filename or "document.docx").rsplit(".", 1)[0]
    return {"download_id": download_id, "filename": f"{base}-updated.docx"}


@api_router.get("/download/{download_id}")
async def download(download_id: str, filename: str = "document.docx"):
    path = DOWNLOADS_DIR / f"{download_id}.docx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    return FileResponse(path, media_type=DOCX_MIME, filename=filename)


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
