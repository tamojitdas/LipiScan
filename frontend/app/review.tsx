import Icon from "@react-native-vector-icons/material-design-icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { type ExtractResult, extractText } from "@/src/api";
import { API_BASE, session } from "@/src/session";
import { ENGINE_LABELS, getOcrEngine } from "@/src/settings";
import { makeStyles, useTheme } from "@/src/theme";

export default function Review() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const uri = session.photoUri;
  const [text, setText] = useState("");
  const [prevText, setPrevText] = useState<string | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);

  const cleanupMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/cleanup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        let detail = "AI cleanup failed";
        try {
          detail = (await res.json()).detail ?? detail;
        } catch {}
        throw new Error(detail);
      }
      return res.json() as Promise<{ text: string }>;
    },
    onSuccess: (d) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setPrevText(text);
      setText(d.text);
      setCleanupError(null);
    },
    onError: (e: Error) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setCleanupError(e.message);
    },
  });

  const undoCleanup = () => {
    if (prevText !== null) {
      setText(prevText);
      setPrevText(null);
    }
  };

  const { data, isLoading, isError, error, refetch } = useQuery<ExtractResult>({
    queryKey: ["extract", uri],
    enabled: !!uri,
    retry: false,
    staleTime: Infinity,
    queryFn: async () => extractText(uri!, await getOcrEngine()),
  });

  useEffect(() => {
    if (data) setText(data.text);
  }, [data]);

  useEffect(() => {
    if (!uri) router.replace("/camera");
  }, [uri, router]);

  if (!uri) return null;

  const goAppend = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    session.text = text;
    router.push("/append");
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={16}
    >
      <View style={styles.imageWrap}>
        <Image source={{ uri }} style={{ flex: 1 }} contentFit="contain" />
        <Pressable
          testID="review-back-button"
          style={[styles.roundBtn, { top: insets.top + 8 }]}
          hitSlop={8}
          onPress={() => router.back()}
        >
          <Icon name="arrow-left" size={22} color={colors.onSurfaceInverse} />
        </Pressable>
      </View>

      <View style={[styles.panel, { paddingBottom: insets.bottom + 16 }]}>
        <View style={styles.handle} />
        <View style={styles.titleRow}>
          <Text style={styles.panelTitle}>Extracted Text</Text>
          {!isLoading && !isError ? (
            prevText !== null ? (
              <Pressable testID="review-undo-cleanup-button" style={styles.aiBtn} onPress={undoCleanup}>
                <Icon name="undo-variant" size={16} color={colors.onBrandTertiary} />
                <Text style={styles.aiBtnText}>Undo</Text>
              </Pressable>
            ) : (
              <Pressable
                testID="review-ai-cleanup-button"
                style={[styles.aiBtn, (!text.trim() || cleanupMutation.isPending) && styles.disabledBtn]}
                disabled={!text.trim() || cleanupMutation.isPending}
                onPress={() => cleanupMutation.mutate()}
              >
                {cleanupMutation.isPending ? (
                  <ActivityIndicator size="small" color={colors.onBrandTertiary} />
                ) : (
                  <Icon name="auto-fix" size={16} color={colors.onBrandTertiary} />
                )}
                <Text style={styles.aiBtnText}>
                  {cleanupMutation.isPending ? "Cleaning…" : "AI Cleanup"}
                </Text>
              </Pressable>
            )
          ) : null}
        </View>
        {cleanupError ? (
          <Text style={styles.cleanupErrorText} testID="review-cleanup-error">
            {cleanupError}
          </Text>
        ) : null}
        {data?.engine === "tesseract" ? (
          <Text style={styles.fallbackHint} testID="review-fallback-hint">
            AI readers were unavailable, so offline OCR was used — results may be rough. Tap AI
            Cleanup or retry.
          </Text>
        ) : data?.engine ? (
          <Text style={styles.engineHint} testID="review-engine-hint">
            Read by {ENGINE_LABELS[data.engine]}
          </Text>
        ) : null}
        {isLoading ? (
          <View style={styles.center} testID="review-loading">
            <ActivityIndicator color={colors.brandPrimary} size="large" />
            <Text style={styles.loadingText}>
              Reading your handwriting line by line, then proofreading it — this can take up to a
              minute.
            </Text>
          </View>
        ) : isError ? (
          <View style={styles.center} testID="review-error">
            <Icon name="alert-circle-outline" size={36} color={colors.error} />
            <Text style={styles.errorText}>{(error as Error)?.message ?? "OCR extraction failed"}</Text>
            <Pressable testID="review-retry-button" style={styles.primaryBtn} onPress={() => refetch()}>
              <Text style={styles.primaryBtnText}>Retry</Text>
            </Pressable>
          </View>
        ) : (
          <>
            {data && !data.text ? (
              <Text style={styles.emptyHint} testID="review-no-text-hint">
                No text was detected. You can type it manually below, or retake the photo.
              </Text>
            ) : null}
            <TextInput
              testID="review-text-input"
              style={styles.input}
              multiline
              value={text}
              onChangeText={(t) => {
                setText(t);
                if (cleanupError) setCleanupError(null);
              }}
              placeholder="Edit the extracted text here…"
              placeholderTextColor={colors.muted}
              textAlignVertical="top"
            />
            <Pressable
              testID="review-append-button"
              style={[styles.primaryBtn, !text.trim() && styles.disabledBtn]}
              disabled={!text.trim()}
              onPress={goAppend}
            >
              <Icon name="file-word-box" size={18} color={colors.onBrandPrimary} />
              <Text style={styles.primaryBtnText}>Append to Document</Text>
            </Pressable>
          </>
        )}
      </View>
    </KeyboardAvoidingView>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surfaceInverse },
  imageWrap: { height: "32%", backgroundColor: colors.surfaceInverse },
  roundBtn: {
    position: "absolute",
    left: 16,
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  panel: {
    flex: 1,
    backgroundColor: colors.surface,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    padding: 20,
    gap: 12,
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
  },
  panelTitle: { fontFamily: "Outfit", fontSize: 20, color: colors.onSurface, fontWeight: "600" },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  aiBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 16,
    height: 38,
    borderRadius: 999,
  },
  aiBtnText: { fontFamily: "Figtree", fontSize: 13, color: colors.onBrandTertiary, fontWeight: "700" },
  cleanupErrorText: { fontFamily: "Figtree", fontSize: 12, color: colors.error },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12, padding: 16 },
  loadingText: { fontFamily: "Figtree", fontSize: 14, color: colors.muted, textAlign: "center" },
  errorText: { fontFamily: "Figtree", fontSize: 14, color: colors.error, textAlign: "center" },
  emptyHint: { fontFamily: "Figtree", fontSize: 13, color: colors.warning },
  fallbackHint: { fontFamily: "Figtree", fontSize: 12, color: colors.warning, lineHeight: 17 },
  engineHint: { fontFamily: "Figtree", fontSize: 12, color: colors.muted },
  input: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 16,
    padding: 16,
    fontFamily: "Figtree",
    fontSize: 16,
    lineHeight: 24,
    color: colors.onSurfaceSecondary,
  },
  primaryBtn: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    height: 54,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  disabledBtn: { opacity: 0.5 },
  primaryBtnText: { fontFamily: "Outfit", color: colors.onBrandPrimary, fontSize: 16, fontWeight: "600" },
}));
