import Icon from "@react-native-vector-icons/material-design-icons";
import { useMutation } from "@tanstack/react-query";
import * as DocumentPicker from "expo-document-picker";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import * as Sharing from "expo-sharing";
import { useState } from "react";
import { ActivityIndicator, Linking, Platform, Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import Animated, { FadeIn, FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { nativeFilePart, postForm } from "@/src/api";
import { API_BASE, session } from "@/src/session";
import { makeStyles, useTheme } from "@/src/theme";

const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

type PickedFile = { uri: string; name: string; size?: number; file?: File };

export default function Append() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [picked, setPicked] = useState<PickedFile | null>(null);
  const [position, setPosition] = useState<"end" | "after_heading">("end");
  const [heading, setHeading] = useState("");
  const [done, setDone] = useState<{ filename: string; url: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const pickFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: [DOCX_MIME],
      copyToCacheDirectory: true,
    });
    if (!result.canceled && result.assets[0]) {
      const a = result.assets[0];
      setPicked({ uri: a.uri, name: a.name, size: a.size ?? undefined, file: (a as any).file });
      setDone(null);
    }
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      if (Platform.OS === "web" && picked!.file) {
        form.append("file", picked!.file, picked!.name);
      } else if (Platform.OS === "web") {
        const blob = await (await fetch(picked!.uri)).blob();
        form.append("file", blob, picked!.name);
      } else {
        form.append("file", nativeFilePart(picked!.uri), picked!.name);
      }
      form.append("text", session.text);
      form.append("position", position);
      form.append("heading", heading);
      return postForm<{ download_id: string; filename: string }>("/append-docx", form);
    },
    onSuccess: async (res) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      const url = `${API_BASE}/download/${res.download_id}?filename=${encodeURIComponent(res.filename)}`;
      setDone({ filename: res.filename, url });
    },
    onError: (e: Error) => {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      showToast(e.message);
    },
  });

  const shareFile = async () => {
    if (!done) return;
    try {
      if (Platform.OS === "web") {
        Linking.openURL(done.url);
        return;
      }
      const FileSystem = await import("expo-file-system/legacy");
      const dest = `${FileSystem.cacheDirectory}${done.filename}`;
      const dl = await FileSystem.downloadAsync(done.url, dest);
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(dl.uri, { mimeType: DOCX_MIME, dialogTitle: done.filename });
      } else {
        showToast("Sharing is not available on this device");
      }
    } catch {
      showToast("Could not download the file");
    }
  };

  const canSave = !!picked && (position === "end" || heading.trim().length > 0);

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <Pressable testID="append-back-button" hitSlop={10} onPress={() => router.back()}>
          <Icon name="arrow-left" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Append to Document</Text>
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, paddingBottom: 140, gap: 16 }}
        bottomOffset={90}
      >
        {/* Text preview */}
        <View style={styles.previewCard}>
          <Text style={styles.sectionLabel}>Text to append</Text>
          <Text style={styles.previewText} numberOfLines={5} testID="append-text-preview">
            {session.text || "(no text)"}
          </Text>
        </View>

        {/* File picker */}
        <Text style={styles.sectionLabel}>Target document</Text>
        {picked ? (
          <Animated.View entering={FadeIn} style={styles.fileCard} testID="append-selected-file">
            <View style={styles.fileIcon}>
              <Icon name="file-word" size={24} color={colors.onBrandTertiary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.fileName} numberOfLines={1}>
                {picked.name}
              </Text>
              {picked.size ? (
                <Text style={styles.fileMeta}>{(picked.size / 1024).toFixed(1)} KB</Text>
              ) : null}
            </View>
            <Pressable testID="append-change-file-button" hitSlop={8} onPress={pickFile}>
              <Text style={styles.changeText}>Change</Text>
            </Pressable>
          </Animated.View>
        ) : (
          <Pressable testID="append-browse-button" style={styles.browseBtn} onPress={pickFile}>
            <Icon name="folder-open-outline" size={20} color={colors.onSurfaceSecondary} />
            <Text style={styles.browseText}>Browse device for a .docx file</Text>
          </Pressable>
        )}

        {/* Position selector */}
        {picked ? (
          <Animated.View entering={FadeInDown} style={{ gap: 12 }}>
            <Text style={styles.sectionLabel}>Insert position</Text>
            <View style={styles.segment}>
              <Pressable
                testID="append-position-end"
                style={[styles.segmentItem, position === "end" && styles.segmentActive]}
                onPress={() => setPosition("end")}
              >
                <Text style={[styles.segmentText, position === "end" && styles.segmentTextActive]}>
                  End of document
                </Text>
              </Pressable>
              <Pressable
                testID="append-position-heading"
                style={[styles.segmentItem, position === "after_heading" && styles.segmentActive]}
                onPress={() => setPosition("after_heading")}
              >
                <Text
                  style={[styles.segmentText, position === "after_heading" && styles.segmentTextActive]}
                >
                  After a heading
                </Text>
              </Pressable>
            </View>
            {position === "after_heading" ? (
              <TextInput
                testID="append-heading-input"
                style={styles.headingInput}
                value={heading}
                onChangeText={setHeading}
                placeholder="Type the heading text to insert after…"
                placeholderTextColor={colors.muted}
              />
            ) : null}
          </Animated.View>
        ) : null}

        {/* Success card */}
        {done ? (
          <Animated.View entering={FadeInDown} style={styles.successCard} testID="append-success-card">
            <Icon name="check-circle" size={28} color={colors.success} />
            <Text style={styles.successTitle}>Document updated!</Text>
            <Text style={styles.successText}>{done.filename}</Text>
            <Pressable testID="append-share-button" style={styles.primaryBtn} onPress={shareFile}>
              <Icon name="share-variant" size={18} color={colors.onBrandPrimary} />
              <Text style={styles.primaryBtnText}>
                {Platform.OS === "web" ? "Download File" : "Save / Share File"}
              </Text>
            </Pressable>
            <Pressable
              testID="append-done-button"
              style={styles.secondaryBtn}
              onPress={() => router.dismissTo("/")}
            >
              <Text style={styles.secondaryBtnText}>Done</Text>
            </Pressable>
          </Animated.View>
        ) : null}
      </KeyboardAwareScrollView>

      {/* Sticky CTA */}
      {!done ? (
        <View style={[styles.stickyBar, { paddingBottom: insets.bottom + 16 }]}>
          <Pressable
            testID="append-save-button"
            style={[styles.primaryBtn, (!canSave || saveMutation.isPending) && styles.disabledBtn]}
            disabled={!canSave || saveMutation.isPending}
            onPress={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? (
              <ActivityIndicator color={colors.onBrandPrimary} />
            ) : (
              <>
                <Icon name="content-save" size={18} color={colors.onBrandPrimary} />
                <Text style={styles.primaryBtnText}>Save Document</Text>
              </>
            )}
          </Pressable>
        </View>
      ) : null}

      {/* Toast */}
      {toast ? (
        <Animated.View
          entering={FadeInDown}
          style={[styles.toast, { bottom: insets.bottom + 100 }]}
          testID="append-toast"
        >
          <Icon name="alert-circle" size={18} color={colors.onError} />
          <Text style={styles.toastText}>{toast}</Text>
        </Animated.View>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 16,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  title: { fontFamily: "Outfit", fontSize: 20, color: colors.onSurface, fontWeight: "600" },
  sectionLabel: {
    fontFamily: "Figtree",
    fontSize: 13,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  previewCard: { backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 16, gap: 8 },
  previewText: { fontFamily: "Figtree", fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  browseBtn: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.borderStrong,
    borderRadius: 16,
    height: 64,
  },
  browseText: { fontFamily: "Figtree", fontSize: 15, color: colors.onSurfaceSecondary, fontWeight: "600" },
  fileCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.brandTertiary,
    borderRadius: 16,
    padding: 16,
  },
  fileIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  fileName: { fontFamily: "Outfit", fontSize: 15, color: colors.onBrandTertiary, fontWeight: "600" },
  fileMeta: { fontFamily: "Figtree", fontSize: 12, color: colors.onBrandTertiary, opacity: 0.7 },
  changeText: { fontFamily: "Figtree", color: colors.brandPrimary, fontWeight: "700" },
  segment: {
    flexDirection: "row",
    backgroundColor: colors.surfaceTertiary,
    borderRadius: 999,
    padding: 4,
  },
  segmentItem: {
    flex: 1,
    height: 42,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  segmentActive: { backgroundColor: colors.brandPrimary },
  segmentText: { fontFamily: "Figtree", fontSize: 13, color: colors.onSurfaceTertiary, fontWeight: "600" },
  segmentTextActive: { color: colors.onBrandPrimary },
  headingInput: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 12,
    paddingHorizontal: 16,
    height: 52,
    fontFamily: "Figtree",
    fontSize: 15,
    color: colors.onSurfaceSecondary,
  },
  successCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 20,
    padding: 24,
    alignItems: "center",
    gap: 10,
  },
  successTitle: { fontFamily: "Outfit", fontSize: 20, color: colors.onSurface, fontWeight: "600" },
  successText: { fontFamily: "Figtree", fontSize: 13, color: colors.muted },
  stickyBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 16,
    paddingTop: 12,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  primaryBtn: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    height: 54,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "stretch",
  },
  disabledBtn: { opacity: 0.5 },
  primaryBtnText: { fontFamily: "Outfit", color: colors.onBrandPrimary, fontSize: 16, fontWeight: "600" },
  secondaryBtn: {
    backgroundColor: colors.surfaceTertiary,
    height: 48,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "stretch",
  },
  secondaryBtnText: { fontFamily: "Figtree", color: colors.onSurfaceTertiary, fontWeight: "600" },
  toast: {
    position: "absolute",
    left: 24,
    right: 24,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    backgroundColor: colors.error,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  toastText: { flex: 1, fontFamily: "Figtree", color: colors.onError, fontSize: 13 },
}));
