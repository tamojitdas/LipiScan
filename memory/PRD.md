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
- POST /api/extract (image) → {id, text} + history record
- GET /api/history, DELETE /api/history/{id} (soft delete)
- POST /api/append-docx (docx, text, position=end|after_heading, heading) → {download_id, filename}
- GET /api/download/{download_id}

## Implemented (June 2026 — MVP)
- Camera capture with corner-bracket guide frame overlay, permission flow (pre-permission explainer, Open Settings fallback), gallery picker fallback
- Quality check screen (bottom sheet: 3 checks, Retake / Proceed Anyway / Extract Text)
- OCR review screen (split image + editable text, Bengali+English)
- DOCX append screen (document picker, End/After-heading segmented control, save, download & share via expo-sharing)
- History home with soft delete, empty state, FAB
- Tested: 16/16 backend pytest + frontend flows pass (testing agent iteration 1)

## Backlog
- P1: Store captured image thumbnails (Emergent Object Storage) in history cards
- P1: LLM cleanup pass on OCR text (Emergent LLM key) for handwriting accuracy
- P2: Batch multi-page capture into one document
- P2: Dark theme
- Note: real camera capture requires device testing (Expo Go); web preview shows permission gate only.
