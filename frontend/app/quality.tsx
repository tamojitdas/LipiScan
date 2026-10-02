import Icon from "@react-native-vector-icons/material-design-icons";
import { useQuery } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import Animated, { SlideInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { buildImageForm, postForm, type QualityResult } from "@/src/api";
import { session } from "@/src/session";
import { makeStyles, useTheme } from "@/src/theme";

const CHECKS: { code: string; label: string; icon: string }[] = [
  { code: "blur", label: "Sharpness", icon: "blur" },
  { code: "dim", label: "Lighting", icon: "brightness-6" },
  { code: "no_text", label: "Text detected", icon: "text-recognition" },
];

export default function Quality() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const uri = session.photoUri;

  useEffect(() => {
    if (!uri) router.replace("/camera");
  }, [uri, router]);

  const { data, isLoading, isError, error, refetch } = useQuery<QualityResult>({
    queryKey: ["quality", uri],
    enabled: !!uri,
    retry: false,
    queryFn: async () => {
      const form = await buildImageForm(uri!);
      return postForm<QualityResult>("/quality-check", form);
    },
  });

  if (!uri) return null;

  const retake = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.back();
  };
  const proceed = () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    router.push("/review");
  };

  const issueCodes = new Set((data?.issues ?? []).map((i) => i.code));

  return (
    <View style={styles.root}>
      <Image source={{ uri }} style={StyleSheet.absoluteFill} contentFit="contain" />
      <View style={[styles.topBar, { top: insets.top + 8 }]}>
        <Pressable testID="quality-close-button" style={styles.roundBtn} hitSlop={8} onPress={retake}>
          <Icon name="close" size={22} color={colors.onSurfaceInverse} />
        </Pressable>
      </View>

      <Animated.View
        entering={SlideInDown.springify().damping(18)}
        style={styles.sheet}
        testID="quality-sheet"
      >
        <View style={styles.handle} />
        <ScrollView
          testID="quality-sheet-scroll"
          style={styles.sheetScroll}
          contentContainerStyle={[styles.sheetContent, { paddingBottom: insets.bottom + 20 }]}
          showsVerticalScrollIndicator
        >
        {isLoading ? (
          <View style={styles.loadingRow}>
            <ActivityIndicator color={colors.brandPrimary} />
            <Text style={styles.loadingText}>Validating image quality…</Text>
          </View>
        ) : isError ? (
          <>
            <Text style={styles.sheetTitle}>Check failed</Text>
            <Text style={styles.issueText}>{(error as Error)?.message ?? "Could not analyze image"}</Text>
            <Pressable testID="quality-retry-button" style={styles.primaryBtn} onPress={() => refetch()}>
              <Text style={styles.primaryBtnText}>Retry</Text>
            </Pressable>
            <Pressable testID="quality-retake-button" style={styles.secondaryBtn} onPress={retake}>
              <Text style={styles.secondaryBtnText}>Retake</Text>
            </Pressable>
          </>
        ) : data ? (
          <>
            <Text style={styles.sheetTitle} testID="quality-result-title">
              {data.ok ? "Looks good!" : "Quality issues found"}
            </Text>
            {CHECKS.map((check) => {
              const failed = issueCodes.has(check.code);
              return (
                <View key={check.code} style={styles.checkRow} testID={`quality-check-${check.code}`}>
                  <Icon name={check.icon as any} size={20} color={failed ? colors.error : colors.success} />
                  <Text style={styles.checkLabel}>{check.label}</Text>
                  <Icon
                    name={failed ? "alert-circle" : "check-circle"}
                    size={20}
                    color={failed ? colors.error : colors.success}
                  />
                </View>
              );
            })}
            {(data.issues ?? []).map((issue) => (
              <Text key={issue.code} style={styles.issueText}>
                {issue.message}
              </Text>
            ))}
            {data.ok ? (
              <>
                <Pressable testID="quality-extract-button" style={styles.primaryBtn} onPress={proceed}>
                  <Icon name="text-recognition" size={18} color={colors.onBrandPrimary} />
                  <Text style={styles.primaryBtnText}>Extract Text</Text>
                </Pressable>
                <Pressable testID="quality-retake-button" style={styles.secondaryBtn} onPress={retake}>
                  <Text style={styles.secondaryBtnText}>Retake</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Pressable testID="quality-retake-button" style={styles.primaryBtn} onPress={retake}>
                  <Icon name="camera-retake" size={18} color={colors.onBrandPrimary} />
                  <Text style={styles.primaryBtnText}>Retake</Text>
                </Pressable>
                <Pressable testID="quality-proceed-anyway-button" style={styles.secondaryBtn} onPress={proceed}>
                  <Text style={styles.secondaryBtnText}>Proceed Anyway</Text>
                </Pressable>
              </>
            )}
          </>
        ) : null}
        </ScrollView>
      </Animated.View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surfaceInverse },
  topBar: { position: "absolute", left: 16, right: 16, flexDirection: "row", zIndex: 2 },
  roundBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    maxHeight: "78%",
    backgroundColor: colors.surface,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    paddingTop: 12,
  },
  sheetScroll: { flexGrow: 0 },
  sheetContent: { paddingHorizontal: 24, paddingTop: 8, gap: 12 },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    marginBottom: 4,
  },
  loadingRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 24 },
  loadingText: { fontFamily: "Figtree", fontSize: 15, color: colors.onSurface },
  sheetTitle: { fontFamily: "Outfit", fontSize: 22, color: colors.onSurface, fontWeight: "600" },
  checkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  checkLabel: { flex: 1, fontFamily: "Figtree", fontSize: 15, color: colors.onSurfaceSecondary },
  issueText: { fontFamily: "Figtree", fontSize: 13, color: colors.error, lineHeight: 18 },
  primaryBtn: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    height: 54,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
  },
  primaryBtnText: { fontFamily: "Outfit", color: colors.onBrandPrimary, fontSize: 16, fontWeight: "600" },
  secondaryBtn: {
    backgroundColor: colors.surfaceSecondary,
    height: 50,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryBtnText: { fontFamily: "Figtree", color: colors.onSurfaceSecondary, fontSize: 15, fontWeight: "600" },
}));
