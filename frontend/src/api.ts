import { File as FsFile } from "expo-file-system";
import { Platform } from "react-native";

import { API_BASE } from "@/src/session";

// Expo SDK 54+ ships a WinterCG-compliant fetch/FormData, which rejects the
// legacy React Native `{ uri, name, type }` part ("Unsupported FormDataPart
// implementation"). expo-file-system's `File` implements Blob, so it works.
export function nativeFilePart(uri: string) {
  return new FsFile(uri) as unknown as Blob;
}

export async function buildImageForm(uri: string): Promise<FormData> {
  const form = new FormData();
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    form.append("file", blob, "photo.jpg");
  } else {
    form.append("file", nativeFilePart(uri), "photo.jpg");
  }
  return form;
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export interface ExtractResult {
  id: string;
  text: string;
  engine?: "gemini-pro" | "gemini-flash" | "gemma" | "tesseract";
}

interface ExtractJob extends Partial<ExtractResult> {
  job_id: string;
  status: "processing" | "done" | "error";
  detail?: string;
}

/**
 * Extraction takes longer than the request timeout allowed by the ingress, so the
 * backend runs it as a job and we poll until it finishes.
 */
export async function extractText(
  uri: string,
  engine: string,
  maxWaitMs = 5 * 60 * 1000,
): Promise<ExtractResult> {
  const form = await buildImageForm(uri);
  form.append("engine", engine);
  const started = await postForm<ExtractJob>("/extract", form);

  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    const res = await fetch(`${API_BASE}/extract/${started.job_id}`);
    if (!res.ok) throw new Error("Could not check extraction status");
    const job = (await res.json()) as ExtractJob;
    if (job.status === "done") {
      return { id: job.id!, text: job.text ?? "", engine: job.engine };
    }
    if (job.status === "error") {
      throw new Error(job.detail ?? "Extraction failed");
    }
  }
  throw new Error("Extraction timed out. Please try again with a clearer photo.");
}

export interface QualityIssue {
  code: string;
  label: string;
  message: string;
}

export interface QualityResult {
  ok: boolean;
  blur_score: number;
  brightness: number;
  has_text: boolean;
  issues: QualityIssue[];
}

export interface HistoryItem {
  id: string;
  text: string;
  snippet: string;
  char_count: number;
  created_at: string;
}
