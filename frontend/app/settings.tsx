import Icon from "@react-native-vector-icons/material-design-icons";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getOcrEngine, OCR_ENGINES, setOcrEngine, type OcrEngine } from "@/src/settings";
import { makeStyles, useTheme } from "@/src/theme";

export default function Settings() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const [engine, setEngine] = useState<OcrEngine | null>(null);

  useEffect(() => {
    getOcrEngine().then(setEngine);
  }, []);

  const choose = async (value: OcrEngine) => {
    Haptics.selectionAsync();
    setEngine(value);
    await setOcrEngine(value);
  };

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <Pressable testID="settings-back-button" hitSlop={10} onPress={() => router.back()}>
          <Icon name="arrow-left" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Settings</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 12 }}>
        <Text style={styles.sectionTitle}>OCR engine</Text>
        <Text style={styles.sectionHint}>
          Which AI model reads your handwriting. If the chosen model fails, the other one is tried
          automatically, and offline Tesseract OCR is the final fallback.
        </Text>

        {engine === null ? (
          <View style={styles.loading}>
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        ) : (
          OCR_ENGINES.map((option) => {
            const selected = option.value === engine;
            return (
              <Pressable
                key={option.value}
                testID={`settings-engine-${option.value}`}
                style={[styles.option, selected && styles.optionSelected]}
                onPress={() => choose(option.value)}
              >
                <View style={styles.optionIcon}>
                  <Icon name={option.icon as any} size={20} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.optionLabel}>{option.label}</Text>
                  <Text style={styles.optionDesc}>{option.description}</Text>
                </View>
                <Icon
                  name={selected ? "radiobox-marked" : "radiobox-blank"}
                  size={22}
                  color={selected ? colors.brandPrimary : colors.muted}
                />
              </Pressable>
            );
          })
        )}
      </ScrollView>
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
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  title: { fontFamily: "Outfit", fontSize: 22, color: colors.onSurface, fontWeight: "600" },
  sectionTitle: { fontFamily: "Outfit", fontSize: 17, color: colors.onSurface, fontWeight: "600" },
  sectionHint: { fontFamily: "Figtree", fontSize: 13, color: colors.muted, lineHeight: 19 },
  loading: { paddingVertical: 32, alignItems: "center" },
  option: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 20,
    padding: 16,
    borderWidth: 2,
    borderColor: "transparent",
  },
  optionSelected: { borderColor: colors.brandPrimary },
  optionIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  optionLabel: { fontFamily: "Outfit", fontSize: 16, color: colors.onSurface, fontWeight: "600" },
  optionDesc: {
    fontFamily: "Figtree",
    fontSize: 12,
    color: colors.muted,
    marginTop: 3,
    lineHeight: 17,
  },
}));
