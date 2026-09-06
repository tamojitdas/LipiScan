// In-memory session for the capture -> quality -> review -> append flow.
export const session = {
  photoUri: null as string | null,
  text: "",
};

export const API_BASE = `${process.env.EXPO_PUBLIC_BACKEND_URL}/api`;
