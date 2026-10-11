import { storage } from "@/src/utils/storage";

export type OcrEngine = "gemini-pro" | "gemini-flash" | "gemma";

export const OCR_ENGINE_KEY = "lipiscan.ocr_engine";

export const DEFAULT_OCR_ENGINE: OcrEngine = "gemini-pro";

export const OCR_ENGINES: { value: OcrEngine; label: string; description: string; icon: string }[] = [
  {
    value: "gemini-pro",
    label: "Best accuracy",
    description:
      "Gemini 3 Flash reads each line, then Gemini 3.1 Pro proofreads the whole page. Takes about a minute on a full page.",
    icon: "star-four-points",
  },
  {
    value: "gemini-flash",
    label: "Fast",
    description: "Gemini 3 Flash only. Around 20 seconds a page, slightly less accurate.",
    icon: "flash",
  },
  {
    value: "gemma",
    label: "Gemma 4 (open model)",
    description: "Gemma 4 31B via Hugging Face. Weakest on Bengali handwriting.",
    icon: "leaf",
  },
];

export async function getOcrEngine(): Promise<OcrEngine> {
  const stored = await storage.getItem(OCR_ENGINE_KEY, DEFAULT_OCR_ENGINE);
  const match = OCR_ENGINES.find((e) => e.value === stored);
  return match ? match.value : DEFAULT_OCR_ENGINE;
}

export async function setOcrEngine(engine: OcrEngine): Promise<void> {
  await storage.setItem(OCR_ENGINE_KEY, engine);
}

export const ENGINE_LABELS: Record<string, string> = {
  "gemini-pro": "Gemini 3 Flash + 3.1 Pro proofread",
  "gemini-flash": "Gemini 3 Flash",
  gemma: "Gemma 4 (31B)",
  tesseract: "Offline OCR (Tesseract)",
};
