// Design tokens for this app. Light theme only.Always modify the colors and theme to Dark, Light or Dark and Light according to the design guidelines.
//
// The keys match the "color" block of /app/design_guidelines.json. Fill the
// values from that file (or from the user's brand colors). Keep every key; do
// not add a second theme or colors file; do not write color literals in
// components.
//
// How the names work: a plain key is a background, and its `on` partner is the
// text or icon color that sits on top of it. Always use them as a pair.
//   <View style={{ backgroundColor: colors.brandPrimary }}>
//     <Text style={{ color: colors.onBrandPrimary }}>Continue</Text>
//   </View>
//
// Styling a screen or component: build the sheet with makeStyles so colors
// and layout live together and follow the active scheme:
//   const useStyles = makeStyles((colors) => ({
//     card: { backgroundColor: colors.surfaceSecondary, padding: 16 },
//     title: { color: colors.onSurfaceSecondary, fontSize: 16 },
//   }));
//   function Screen() {
//     const styles = useStyles();
//     return <View style={styles.card}><Text style={styles.title}>Hi</Text></View>;
//   }
// For color props that are not styles (icon color, placeholderTextColor,
// ActivityIndicator) read useTheme().colors inside the component.
// Never call StyleSheet.create with color values at module level; it cannot
// follow the scheme.
//
// To support dark mode later: add `dark` to `themes` with every key filled.
// Nothing else changes; the device setting takes over automatically.
// Feel free to add as many new colors as you need to support the design guidelines.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  // ---------------------------------------------------------------------------
  // Surfaces: backgrounds, from the screen down to small fills.
  // Each `on` key is the text and icon color for that background.
  // ---------------------------------------------------------------------------
  surface: "#F7F6F2", // primary canvas, most of every screen
  onSurface: "#1A1C19", // text and icons on the canvas
  surfaceSecondary: "#EBE9E0", // cards, sheets, list rows
  onSurfaceSecondary: "#3F4941", // text and icons on cards, sheets, rows
  surfaceTertiary: "#DFDDD4", // input backgrounds, chips, deepest nesting
  onSurfaceTertiary: "#313B33", // text on inputs and chips; also muted text
  surfaceInverse: "#2B322D", // tooltips, snackbars, anything popping against the theme
  onSurfaceInverse: "#F2F1EA", // text and icons on the inverse surface
  muted: "#717871", // subdued text on surface: captions, timestamps, placeholders

  // ---------------------------------------------------------------------------
  // Brand: the identity color and the fills built from it.
  // Neutral by default; replace with the design guidelines values.
  // ---------------------------------------------------------------------------
  brand: "#386650", // base hue, anchor only; Primary, Secondary, Tertiary are weights of it
  onBrand: "#FFFFFF", // text and icons placed directly on brand
  brandPrimary: "#386650", // primary CTA, active tab indicator, selected states
  onBrandPrimary: "#FFFFFF", // text and icons on brandPrimary
  brandSecondary: "#758C7C", // secondary CTA, less prominent accents
  onBrandSecondary: "#FFFFFF", // text and icons on brandSecondary
  brandTertiary: "#CBE3D2", // chips, tags, badges, subtle brand moments
  onBrandTertiary: "#173322", // text and icons on brandTertiary

  // ---------------------------------------------------------------------------
  // Status: semantic only, never decorative. Fill for badges, banners and
  // toasts; the `on` key is text on that fill. The plain key is also safe as
  // text on `surface`.
  // ---------------------------------------------------------------------------
  success: "#287A4F",
  onSuccess: "#FFFFFF",
  warning: "#8F7B2B",
  onWarning: "#FFFFFF",
  error: "#9E2A2B",
  onError: "#FFFFFF",
  info: "#4A6051",
  onInfo: "#FFFFFF",

  // ---------------------------------------------------------------------------
  // Lines
  // ---------------------------------------------------------------------------
  border: "#D4D1C7", // hairline outline, 0.5pt or 1pt max: inputs, cards
  borderStrong: "#8B8E85", // focus rings, selected outlines, 1.5pt max
  divider: "#E1DFD6", // subtle list separators
};

export type ThemeColors = typeof light;

export const defaultScheme = "light" satisfies ColorScheme;

export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

// In-app theme toggle, only after `dark` exists in `themes`. Call
// setColorScheme("dark"), setColorScheme("light"), or setColorScheme(null) to
// follow the device. Every useTheme() consumer re-renders. Persisting the
// choice and re-applying it on launch is the toggle's job.
export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme);
}

// Keep native surfaces (alerts, pickers, navigation chrome) on the schemes this
// app ships: light only forces light; once `dark` exists the device decides.
// Optional call because react-native-web does not implement it.
setColorScheme?.(themes.dark ? null : defaultScheme);

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const scheme: ColorScheme = system && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

// Themed StyleSheet: returns a hook that builds the sheet from the active
// scheme's colors and memoizes it until the scheme changes.
export function makeStyles<T extends StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>>(
  factory: (colors: ThemeColors) => T & StyleSheet.NamedStyles<any>,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}


