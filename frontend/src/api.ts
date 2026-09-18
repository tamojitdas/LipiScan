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
