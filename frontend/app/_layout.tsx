import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { LogBox } from "react-native";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { queryClient } from "@/src/query-client";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    Outfit: require("../assets/fonts/Outfit-SemiBold.ttf"),
    Figtree: require("../assets/fonts/Figtree.ttf"),
  });

  if (!fontsLoaded) return null;

  // One app level ErrorBoundary; a render crash shows a reload screen
  // instead of a blank app.
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <KeyboardProvider>
          <StatusBar style="dark" />
          <Stack screenOptions={{ headerShown: false, animation: "slide_from_right" }} />
        </KeyboardProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
