import Icon from "@react-native-vector-icons/material-design-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { session } from "@/src/session";
import { makeStyles, useTheme } from "@/src/theme";

const { width: SCREEN_W } = Dimensions.get("window");
const FRAME_W = SCREEN_W - 48;
const FRAME_H = FRAME_W * 1.15;

// Camera scrim must stay dark on any theme.
const SCRIM = "rgba(0,0,0,0.55)";
const BRACKET = "#FFFFFF";

function Corner({ pos }: { pos: "tl" | "tr" | "bl" | "br" }) {
  const base = { position: "absolute" as const, width: 34, height: 34, borderColor: BRACKET };
  const map = {
    tl: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 14 },
    tr: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 14 },
    bl: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 14 },
    br: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 14 },
  };
  return <View style={[base, map[pos]]} />;
}

export default function Camera() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const cameraRef = useRef<CameraView>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing] = useState(false);

  const goToQuality = (uri: string) => {
    session.photoUri = uri;
    session.text = "";
    router.push("/quality");
  };

  const capture = async () => {
    if (capturing || !cameraRef.current) return;
    setCapturing(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.7 });
      if (photo?.uri) goToQuality(photo.uri);
    } finally {
      setCapturing(false);
    }
  };

  const pickFromGallery = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.8,
    });
    if (!result.canceled && result.assets[0]?.uri) goToQuality(result.assets[0].uri);
  };

  if (!permission) {
    return (
      <View style={styles.permissionRoot}>
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={[styles.permissionRoot, { paddingTop: insets.top, paddingBottom: insets.bottom + 24 }]}>
        <View style={styles.permissionIcon}>
          <Icon name="camera-outline" size={36} color={colors.onBrandTertiary} />
        </View>
        <Text style={styles.permissionTitle}>Camera access needed</Text>
        <Text style={styles.permissionText}>
          LipiScan uses your camera to capture handwritten notes so the text can be extracted.
        </Text>
        {permission.canAskAgain ? (
          <Pressable testID="camera-grant-button" style={styles.primaryBtn} onPress={requestPermission}>
            <Text style={styles.primaryBtnText}>Enable Camera</Text>
          </Pressable>
        ) : (
          <Pressable
            testID="camera-open-settings-button"
            style={styles.primaryBtn}
            onPress={() => Linking.openSettings()}
          >
            <Text style={styles.primaryBtnText}>Open Settings</Text>
          </Pressable>
        )}
        <Pressable testID="camera-pick-gallery-fallback" style={styles.secondaryBtn} onPress={pickFromGallery}>
          <Text style={styles.secondaryBtnText}>Pick from gallery instead</Text>
        </Pressable>
        <Pressable testID="camera-back-button" hitSlop={12} onPress={() => router.back()}>
          <Text style={styles.linkText}>Go back</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <CameraView ref={cameraRef} style={StyleSheet.absoluteFill} facing="back" />

      {/* Scrim + guide frame */}
      <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
        <View style={[localStyles.scrim, { flex: 1 }]} />
        <View style={{ flexDirection: "row", height: FRAME_H }}>
          <View style={[localStyles.scrim, { flex: 1 }]} />
          <View style={{ width: FRAME_W }}>
            <Corner pos="tl" />
            <Corner pos="tr" />
            <Corner pos="bl" />
            <Corner pos="br" />
          </View>
          <View style={[localStyles.scrim, { flex: 1 }]} />
        </View>
        <View style={[localStyles.scrim, { flex: 1.4, alignItems: "center" }]}>
          <Text style={styles.hint}>Position the handwritten note within the frame</Text>
        </View>
      </View>

      {/* Top bar */}
      <View style={[styles.topBar, { top: insets.top + 8 }]}>
        <Pressable testID="camera-close-button" style={styles.roundBtn} hitSlop={8} onPress={() => router.back()}>
          <Icon name="close" size={22} color={BRACKET} />
        </Pressable>
      </View>

      {/* Bottom controls */}
      <View style={[styles.controls, { bottom: insets.bottom + 28 }]}>
        <Pressable testID="camera-gallery-button" style={styles.roundBtn} onPress={pickFromGallery}>
          <Icon name="image-multiple-outline" size={22} color={BRACKET} />
        </Pressable>
        <Pressable testID="camera-capture-button" style={styles.captureOuter} onPress={capture} disabled={capturing}>
          {capturing ? (
            <ActivityIndicator color={colors.onBrandPrimary} />
          ) : (
            <View style={styles.captureInner} />
          )}
        </Pressable>
        <View style={{ width: 48 }} />
      </View>
    </View>
  );
}

const localStyles = StyleSheet.create({
  scrim: { backgroundColor: SCRIM },
});

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surfaceInverse },
  hint: {
    fontFamily: "Figtree",
    color: BRACKET,
    fontSize: 14,
    marginTop: 20,
    paddingHorizontal: 32,
    textAlign: "center",
  },
  topBar: { position: "absolute", left: 16, right: 16, flexDirection: "row" },
  roundBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  controls: {
    position: "absolute",
    left: 0,
    right: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-evenly",
  },
  captureOuter: {
    width: 78,
    height: 78,
    borderRadius: 39,
    borderWidth: 4,
    borderColor: BRACKET,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandPrimary,
  },
  captureInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: colors.onBrandPrimary },
  permissionRoot: {
    flex: 1,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    gap: 14,
  },
  permissionIcon: {
    width: 72,
    height: 72,
    borderRadius: 24,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  permissionTitle: { fontFamily: "Outfit", fontSize: 22, color: colors.onSurface, fontWeight: "600" },
  permissionText: {
    fontFamily: "Figtree",
    fontSize: 14,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 28,
    height: 52,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: { fontFamily: "Outfit", color: colors.onBrandPrimary, fontSize: 16, fontWeight: "600" },
  secondaryBtn: {
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 24,
    height: 48,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryBtnText: { fontFamily: "Figtree", color: colors.onSurfaceSecondary, fontWeight: "600" },
  linkText: { fontFamily: "Figtree", color: colors.muted, textDecorationLine: "underline" },
}));
