import Icon from "@react-native-vector-icons/material-design-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_BASE } from "@/src/session";
import type { HistoryItem } from "@/src/api";
import { makeStyles, useTheme } from "@/src/theme";

const EMPTY_IMG =
  "https://images.unsplash.com/photo-1600172454132-ada7faa101cf?crop=entropy&cs=srgb&fm=jpg&q=85&w=800";

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " · " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function History() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery<HistoryItem[]>({
    queryKey: ["history"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/history`);
      if (!res.ok) throw new Error("Failed to load history");
      return res.json();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${API_BASE}/history/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <View>
          <Text style={styles.title}>LipiScan</Text>
          <Text style={styles.subtitle}>Bengali & English handwriting to Word</Text>
        </View>
      </View>

      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
        </View>
      ) : isError ? (
        <View style={styles.center} testID="history-error">
          <Icon name="cloud-alert" size={40} color={colors.muted} />
          <Text style={styles.emptyText}>Failed to load history</Text>
          <Pressable testID="history-retry-button" style={styles.secondaryBtn} onPress={() => refetch()}>
            <Text style={styles.secondaryBtnText}>Retry</Text>
          </Pressable>
        </View>
      ) : !data || data.length === 0 ? (
        <View style={styles.center} testID="history-empty">
          <Image source={{ uri: EMPTY_IMG }} style={styles.emptyImage} contentFit="cover" />
          <Text style={styles.emptyTitle}>No scans yet</Text>
          <Text style={styles.emptyText}>
            Capture a handwritten note to extract Bengali or English text and append it to a Word
            document.
          </Text>
        </View>
      ) : (
        <FlatList
          testID="history-list"
          data={data}
          keyExtractor={(item) => item.id}
          contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 120 }}
          renderItem={({ item, index }) => (
            <Animated.View entering={FadeInDown.delay(Math.min(index * 60, 300))}>
              <View style={styles.card} testID={`history-card-${index}`}>
                <View style={styles.cardIcon}>
                  <Icon name="text-recognition" size={22} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardSnippet} numberOfLines={3}>
                    {item.snippet || "(empty)"}
                  </Text>
                  <Text style={styles.cardMeta}>
                    {formatDate(item.created_at)} · {item.char_count} chars
                  </Text>
                </View>
                <Pressable
                  testID={`history-delete-${index}`}
                  hitSlop={10}
                  onPress={() => deleteMutation.mutate(item.id)}
                >
                  <Icon name="trash-can-outline" size={20} color={colors.muted} />
                </Pressable>
              </View>
            </Animated.View>
          )}
        />
      )}

      <Pressable
        testID="new-scan-fab"
        style={[styles.fab, { bottom: insets.bottom + 24 }]}
        onPress={() => router.push("/camera")}
      >
        <Icon name="camera-plus" size={22} color={colors.onBrandPrimary} />
        <Text style={styles.fabText}>New Scan</Text>
      </Pressable>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: 16,
    paddingBottom: 16,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  title: { fontFamily: "Outfit", fontSize: 28, color: colors.onSurface, fontWeight: "600" },
  subtitle: { fontFamily: "Figtree", fontSize: 14, color: colors.muted, marginTop: 2 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32, gap: 12 },
  emptyImage: { width: 180, height: 130, borderRadius: 20, marginBottom: 8 },
  emptyTitle: { fontFamily: "Outfit", fontSize: 20, color: colors.onSurface, fontWeight: "600" },
  emptyText: {
    fontFamily: "Figtree",
    fontSize: 14,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
  },
  secondaryBtn: {
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 999,
  },
  secondaryBtnText: { fontFamily: "Figtree", color: colors.onSurfaceSecondary, fontWeight: "600" },
  card: {
    flexDirection: "row",
    gap: 12,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 20,
    padding: 16,
    marginBottom: 12,
    alignItems: "flex-start",
  },
  cardIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  cardSnippet: {
    fontFamily: "Figtree",
    fontSize: 14,
    color: colors.onSurfaceSecondary,
    lineHeight: 20,
  },
  cardMeta: { fontFamily: "Figtree", fontSize: 12, color: colors.muted, marginTop: 6 },
  fab: {
    position: "absolute",
    right: 20,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 22,
    height: 56,
    borderRadius: 999,
  },
  fabText: { fontFamily: "Outfit", color: colors.onBrandPrimary, fontSize: 16, fontWeight: "600" },
}));
