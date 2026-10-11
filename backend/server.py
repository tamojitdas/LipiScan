import asyncio
import base64
import io
import logging
import os
import re
import shutil
import subprocess
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional

import cv2
import httpx
import numpy as np
import pytesseract
from bson import ObjectId
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
            [
                "apt-get",
                "install",
                "-y",
                "-qq",
                "tesseract-ocr",
                "tesseract-ocr-ben",
                "tesseract-ocr-eng",
                "fonts-lohit-beng-bengali",
            ],
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


def _crop_document(gray: np.ndarray) -> np.ndarray:
    """Trim the desk/background around the sheet of paper.

    Deliberately conservative: a plain bounding-box crop of the bright paper
    region (no perspective warp), because phone photos often cut the page edge
    and an aggressive warp would slice off text.
    """
    h, w = gray.shape[:2]
    blurred = cv2.GaussianBlur(gray, (9, 9), 0)
    paper = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.3 * h * w:
        return gray
    x, y, cw, ch = cv2.boundingRect(largest)
    pad = max(4, min(h, w) // 100)
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(w, x + cw + pad), min(h, y + ch + pad)
    if (x1 - x0) < 0.5 * w or (y1 - y0) < 0.5 * h:
        return gray
    return gray[y0:y1, x0:x1]


def _scale_to(img: np.ndarray, target_max_dim: int, max_upscale: float = 2.5) -> np.ndarray:
    """Scale so the longest side is ~target (up or down, upscaling is capped)."""
    h, w = img.shape[:2]
    current = max(h, w)
    factor = target_max_dim / current
    if factor > 1:
        factor = min(factor, max_upscale)
    if abs(factor - 1) < 0.02:
        return img
    interp = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=interp)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Straighten a slightly rotated page — handwriting OCR is sensitive to skew."""
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(bw)
    if coords is None:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.4 or abs(angle) > 15:
        return gray
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _enhance(gray: np.ndarray) -> np.ndarray:
    """Even out lighting and boost local contrast so faint pen strokes survive."""
    background = cv2.medianBlur(gray, 31)
    flat = cv2.divide(gray, background, scale=255)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(flat)


def _to_b64_jpeg(img: np.ndarray, quality: int = 95) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("Could not encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _line_bands(gray: np.ndarray, max_lines_per_band: int = 3) -> List[tuple]:
    """Find handwriting lines via a horizontal projection profile and group them
    into small bands. Transcribing a few lines at a time at high resolution is far
    more accurate than one shrunken full-page pass.

    Expects an enhanced (background-flattened) grayscale page.
    """
    h, w = gray.shape[:2]
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # ignore the outer margins, where page edges and shadows add noise
    core = ink[:, int(0.04 * w) : int(0.96 * w)]
    kernel_w = max(9, core.shape[1] // 80)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3, kernel_w), np.uint8))

    proj = (core > 0).sum(axis=1).astype(float)
    smooth = max(3, h // 400)
    proj = np.convolve(proj, np.ones(smooth) / smooth, mode="same")
    row_threshold = max(0.15 * proj.max(), 0.01 * w)
    min_line_h = max(6, h // 250)

    lines: List[tuple] = []
    start = None
    for i, value in enumerate(proj):
        if value > row_threshold and start is None:
            start = i
        elif value <= row_threshold and start is not None:
            if i - start >= min_line_h:
                lines.append((start, i))
            start = None
    if start is not None and h - start >= min_line_h:
        lines.append((start, h))

    if len(lines) < 4:  # short notes: a single full-page pass is enough
        return []

    bands: List[tuple] = []
    pad = max(10, h // 150)
    for i in range(0, len(lines), max_lines_per_band):
        group = lines[i : i + max_lines_per_band]
        top = max(0, group[0][0] - pad)
        bottom = min(h, group[-1][1] + pad)
        bands.append((top, bottom))
    return bands[:16]  # safety cap on model calls


def prepare_vision_inputs(img_bytes: bytes, max_dim: int = 2400, lines_per_band: int = 3) -> dict:
    """Crop the page out of the photo, deskew, flatten lighting, then return the
    full page plus high-resolution line bands, all base64 JPEG."""
    gray = _decode_gray(img_bytes)
    gray = _crop_document(gray)
    gray = _scale_to(gray, max_dim)
    gray = _enhance(_deskew(gray))

    bands = []
    for top, bottom in _line_bands(gray, lines_per_band):
        crop = gray[top:bottom, :]
        if crop.shape[1] < 2000:  # upscale narrow crops for finer strokes
            scale = 2000 / crop.shape[1]
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        bands.append(_to_b64_jpeg(crop))

    return {"page": _to_b64_jpeg(gray), "bands": bands}


LANG_HINT = (
    "The notes are mostly Bengali (Bangla) handwriting and may mix in English words, numbers and "
    "abbreviations. Keep Bengali in Bengali script and English in Latin script. "
    "Pay very close attention to Bengali vowel signs and their length (ি vs ী, ু vs ূ, ে vs ৈ, "
    "ো vs ৌ), to candrabindu (ঁ) and anusvara (ং), to hasanta conjuncts, and to র-ফলা / য-ফলা / "
    "রেফ, which are easy to confuse in cursive handwriting. Use standard Bengali spellings for "
    "common words and names (for example দূর্গা, সরস্বতী, লক্ষ্মী, গণেশ, কৈলাস, মর্ত্যে)."
)

VISION_OCR_SYSTEM = (
    "You are an expert handwriting transcription engine for Bengali (Bangla) and English. "
    f"{LANG_HINT} "
    "Transcribe every word you can read, in reading order, preserving the line and paragraph "
    "structure. Match the handwriting exactly — do not paraphrase, translate, summarise, complete "
    "unfinished sentences or add commentary, headings or explanations that are not on the page. "
    "Correct only obvious letter-shape confusions so the words are real words in their language. "
    "If a word is truly illegible write [?]. "
    "If the image contains no readable text at all, reply with exactly: NO_TEXT_FOUND. "
    "Reply with ONLY the transcribed text — no preamble, no markdown fences."
)

PAGE_PROMPT = "Transcribe all handwritten text in this page image."
BAND_PROMPT = (
    "This is a horizontal strip cropped from a page of handwritten notes. Transcribe only the "
    "text lines visible in this strip, one line per output line."
)
REFINE_SYSTEM = (
    "You are a meticulous proofreader for handwriting transcription of Bengali (Bangla) and "
    f"English notes. {LANG_HINT} "
    "You get the page image and a draft transcription. Compare them word by word and output a "
    "corrected transcription: fix misread characters, wrong words, missing or duplicated lines and "
    "broken conjunct letters, and drop anything that is not actually written on the page. Keep the "
    "original wording, language and line structure. Reply with ONLY the corrected transcription."
)

HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
HF_OCR_MODEL = os.environ.get("HF_OCR_MODEL", "google/gemma-4-31B-it")

# Engine id -> (provider, model). Order here is also the fallback order.
AI_ENGINES: dict = {
    "gemini-pro": ("gemini", "gemini-3.1-pro-preview"),
    "gemini-flash": ("gemini", "gemini-3-flash-preview"),
    "gemma": ("hf", HF_OCR_MODEL),
}
DEFAULT_ENGINE = "gemini-pro"

# Which model drafts the line bands and which one proofreads the page.
# Flash drafts the strips (fast, accurate enough per line) and Pro proofreads the
# whole page — measured as both faster AND more accurate than Pro doing both.
ENGINE_PLAN: dict = {
    "gemini-pro": {"draft": "gemini-flash", "refine": "gemini-pro"},
    "gemini-flash": {"draft": "gemini-flash", "refine": "gemini-flash"},
    "gemma": {"draft": "gemma", "refine": "gemma"},
}


def _finalize_ocr_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.strip())
    if text.upper().startswith("NO_TEXT_FOUND"):
        return ""
    text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text.strip())
    return _clean_text(text)


async def _hf_vision_call(model: str, image_b64: str, prompt: str, system: str) -> str:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise RuntimeError("HF_TOKEN is not configured")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
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
    async with httpx.AsyncClient(timeout=180) as http:
        res = await http.post(
            HF_ROUTER_URL, headers={"Authorization": f"Bearer {token}"}, json=payload
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Hugging Face request failed ({res.status_code}): {res.text[:200]}")
    body = res.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Unexpected Hugging Face response")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


async def _llm_vision_call(model: str, image_b64: str, prompt: str, system: str) -> str:
    chat = LlmChat(
        api_key=os.environ.get("EMERGENT_LLM_KEY", ""),
        session_id=f"ocr-{uuid.uuid4().hex}",
        system_message=system,
    ).with_model("gemini", model)
    result = await chat.send_message(
        UserMessage(text=prompt, file_contents=[ImageContent(image_base64=image_b64)])
    )
    return str(result)


async def vision_call(engine: str, image_b64: str, prompt: str, system: str) -> str:
    provider, model = AI_ENGINES[engine]
    if provider == "hf":
        return await _hf_vision_call(model, image_b64, prompt, system)
    return await _llm_vision_call(model, image_b64, prompt, system)


async def run_ai_ocr(engine: str, img_bytes: bytes) -> str:
    """High-accuracy pipeline: crop/deskew/flatten → line-band drafts → page proofread.

    Raises on model failure so the caller can fall back to another engine.
    """
    plan = ENGINE_PLAN[engine]
    prepared = await asyncio.to_thread(prepare_vision_inputs, img_bytes)

    if prepared["bands"]:
        parts = await asyncio.gather(
            *[
                vision_call(plan["draft"], band, BAND_PROMPT, VISION_OCR_SYSTEM)
                for band in prepared["bands"]
            ]
        )
        draft = "\n".join(p.strip() for p in parts if p.strip() and "NO_TEXT_FOUND" not in p.upper())
    else:
        draft = await vision_call(plan["draft"], prepared["page"], PAGE_PROMPT, VISION_OCR_SYSTEM)

    draft = _finalize_ocr_text(draft)
    if not draft:
        return ""

    try:
        refined = await vision_call(
            plan["refine"],
            prepared["page"],
            f"Draft transcription to verify and correct:\n\n{draft}",
            REFINE_SYSTEM,
        )
        refined = _finalize_ocr_text(refined)
    except Exception:
        logging.exception("refine pass failed; keeping draft")
        return draft

    # A refine pass that throws most of the text away is a bad sign — keep the draft.
    if not refined or len(refined) < 0.5 * len(draft):
        return draft
    return refined


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


async def _run_extract_pipeline(data: bytes, engine: str) -> dict:
    """Run the OCR engine chain and persist a history item. Raises ValueError for
    an undecodable image."""
    preferred = engine if engine in AI_ENGINES else DEFAULT_ENGINE
    order = [preferred] + [e for e in AI_ENGINES if e != preferred]

    text = ""
    used = ""
    errors: List[str] = []
    for name in order:
        try:
            text = await run_ai_ocr(name, data)
            used = name
            break
        except ValueError:
            raise
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logging.warning("%s OCR failed: %s", name, exc)

    if not used:
        logging.error("all vision engines failed: %s", " | ".join(errors))
        text = await asyncio.to_thread(run_ocr_sync, data)
        used = "tesseract"

    item = HistoryItem(
        text=text,
        snippet=text[:140],
        char_count=len(text),
        created_at=datetime.now(timezone.utc),
    )
    res = await db.history.insert_one(item.to_mongo())
    return {"id": str(res.inserted_id), "text": text, "engine": used}


async def _extract_job_worker(job_id: str, data: bytes, engine: str) -> None:
    try:
        result = await _run_extract_pipeline(data, engine)
        update = {"status": "done", **result}
    except ValueError:
        update = {"status": "error", "detail": "Invalid image"}
    except Exception as exc:
        logging.exception("extract job %s failed", job_id)
        update = {"status": "error", "detail": str(exc)[:300]}
    update["finished_at"] = datetime.now(timezone.utc)
    await db.extract_jobs.update_one({"_id": ObjectId(job_id)}, {"$set": update})


@api_router.post("/extract", status_code=202)
async def extract_text(file: UploadFile = File(...), engine: str = Form(DEFAULT_ENGINE)):
    """Start an extraction job. The full pipeline can take over a minute, which is
    longer than the ingress request budget, so the client polls GET /extract/{id}."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        await asyncio.to_thread(_decode_gray, data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image")

    requested = engine if engine in AI_ENGINES else DEFAULT_ENGINE
    res = await db.extract_jobs.insert_one(
        {
            "status": "processing",
            "engine": requested,
            "created_at": datetime.now(timezone.utc),
        }
    )
    job_id = str(res.inserted_id)
    asyncio.create_task(_extract_job_worker(job_id, data, requested))
    return {"job_id": job_id, "status": "processing"}


@api_router.get("/extract/{job_id}")
async def extract_status(job_id: str):
    if not ObjectId.is_valid(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    job = await db.extract_jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = {"job_id": job_id, "status": job["status"], "engine": job.get("engine")}
    if job["status"] == "done":
        payload.update({"id": job.get("id"), "text": job.get("text", "")})
    elif job["status"] == "error":
        payload["detail"] = job.get("detail", "Extraction failed")
    return payload


@api_router.get("/history")
async def get_history():
    docs = await db.history.find({"deleted_at": None}).sort("created_at", -1).to_list(100)
    return [HistoryItem.from_mongo(d).model_dump() for d in docs]


@api_router.delete("/history/{item_id}")
async def delete_history(item_id: str):
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
