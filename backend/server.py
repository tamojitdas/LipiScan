import asyncio
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
import numpy as np
import pytesseract
from docx import Document as DocxDocument
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage
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


def analyze_quality_sync(img_bytes: bytes) -> dict:
    gray = _decode_gray(img_bytes)
    gray = _resize_max(gray, 1200)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    small = _resize_max(gray, 900)
    quick = pytesseract.image_to_string(small, lang="ben+eng", config="--psm 6")
    readable = len([c for c in quick if not c.isspace()])
    has_text = readable >= 3

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
async def extract_text(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        text = await asyncio.to_thread(run_ocr_sync, data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image")

    item = HistoryItem(
        text=text,
        snippet=text[:140],
        char_count=len(text),
        created_at=datetime.now(timezone.utc),
    )
    res = await db.history.insert_one(item.to_mongo())
    return {"id": str(res.inserted_id), "text": text}


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
