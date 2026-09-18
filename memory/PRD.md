# LipiScan — PRD

## Original Problem Statement
User requested a native Android (Kotlin/Jetpack Compose) app for extracting handwritten Bengali/English text from camera photos using on-device OCR/LLM, with quality validation (blur/dim/no-text) and appending extracted text into a local .docx file. Agreed adaptation: Expo (React Native) + FastAPI + MongoDB, backend Tesseract OCR (ben+eng), post-capture quality validation, docx append via python-docx with download/share.

## User Choices
- Platform: Expo (React Native) instead of Kotlin
- OCR: Backend Tesseract (free, open-source, Bengali + English traineddata)
- Quality validation: post-capture (blur via Laplacian variance, brightness mean, quick-OCR text presence) with retake prompts
- DOCX: pick from device, append at end or after a heading, download/share updated file

## Architecture
- Backend: FastAPI (port 8001, /api prefix), Tesseract 5 (ben+eng), OpenCV quality analysis, python-docx append, MongoDB history (soft delete), temp download store /tmp/lipiscan_downloads
- Frontend: Expo Router stack — index (History home) → camera → quality → review → append. Theme: botanical green Material You (design_guidelines.json → src/theme.ts). Fonts: Outfit (display) + Figtree (text). Icons: @react-native-vector-icons/material-design-icons. Keyboard: react-native-keyboard-controller.
- Session flow state in /app/frontend/src/session.ts (in-memory).

## API
- POST /api/quality-check (image) → {ok, blur_score, brightness, has_text, issues[]}
- POST /api/extract (image) → {id, text, engine} + history record (Gemini 3 Flash vision primary, Tesseract fallback)
- GET /api/history, DELETE /api/history/{id} (soft delete)
- POST /api/append-docx (docx, text, position=end|after_heading, heading) → {download_id, filename}
- GET /api/download/{download_id}

## Implemented (June 2026)
### Iteration 3 — AI Vision OCR for handwriting
- Problem: Tesseract garbled handwritten Bengali/English (user-reported wrong results)
- POST /api/extract now uses Gemini 3 Flash vision (`gemini-3-flash-preview` via emergentintegrations + Emergent LLM key) as primary engine — transcribes AND cleans/formats in one pass; Tesseract runs only as offline fallback when the AI call fails. Response adds `engine: "ai" | "tesseract"`
- Image downscaled to 1600px + JPEG re-encode before sending to the model
- Quality check `has_text` is now handwriting-aware: adaptive-threshold ink-density heuristic OR'd with the quick Tesseract probe (handwriting no longer flagged "no text")
- Review screen: AI loading copy, warning hint when the Tesseract fallback was used; manual "AI Cleanup" button retained
- Fixed "Unsupported FormDataPart implementation" upload crash — Expo SDK 57 WinterCG fetch needs `expo-file-system` `File` parts instead of `{uri,name,type}` (src/api.ts, app/append.tsx)

### Iteration 2 — AI Text Cleanup
- POST /api/cleanup: Emergent LLM key (openai gpt-5.4 via emergentintegrations) fixes OCR mistakes and formats Bengali/English text; 400 on empty text
- Review screen: "AI Cleanup" button (spinner while pending, disabled when empty), one-step Undo, inline error that clears on edit
- Backend self-heals missing tesseract system package on startup (fresh-container fix found by testing agent)
- Tested: 20/20 backend pytest (4 new cleanup tests + regressions), home smoke pass

### Iteration 1 — MVP
- Camera capture with corner-bracket guide frame overlay, permission flow (pre-permission explainer, Open Settings fallback), gallery picker fallback
- Quality check screen (bottom sheet: 3 checks, Retake / Proceed Anyway / Extract Text)
- OCR review screen (split image + editable text, Bengali+English)
- DOCX append screen (document picker, End/After-heading segmented control, save, download & share via expo-sharing)
- History home with soft delete, empty state, FAB
- Tested: 16/16 backend pytest + frontend flows pass (testing agent iteration 1)

## Backlog
- P1: Store captured image thumbnails (Emergent Object Storage) in history cards
- P2: Batch multi-page capture into one document
- P2: Dark theme
- Note: real camera capture requires device testing (Expo Go); web preview shows permission gate only.
