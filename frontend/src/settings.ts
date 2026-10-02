import { storage } from "@/src/utils/storage";

export type OcrEngine = "gemma" | "gemini";

export const OCR_ENGINE_KEY = "lipiscan.ocr_engine";

export const OCR_ENGINES: { value: OcrEngine; label: string; description: string; icon: string }[] = [
  {
    value: "gemma",
    label: "Gemma 4 (31B)",
    description: "Google's open model via Hugging Face. Falls back to Gemini if unavailable.",
    icon: "leaf",
  },
  {
    value: "gemini",
    label: "Gemini 3 Flash",
    description: "Fast hosted model, very strong on Bengali handwriting.",
    icon: "flash",
  },
];

export async function getOcrEngine(): Promise<OcrEngine> {
  const stored = await storage.getItem(OCR_ENGINE_KEY, "gemma");
  return stored === "gemini" ? "gemini" : "gemma";
}

export async function setOcrEngine(engine: OcrEngine): Promise<void> {
  await storage.setItem(OCR_ENGINE_KEY, engine);
}

export const ENGINE_LABELS: Record<string, string> = {
  gemma: "Gemma 4 (31B)",
  gemini: "Gemini 3 Flash",
  tesseract: "Offline OCR (Tesseract)",
};
