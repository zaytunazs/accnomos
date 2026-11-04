"use client";

/**
 * Which AI answers first (model routing): the Meta Model API (Muse Spark) or the local model (Muse Glimmer 30B, on
 * the user's own computer when one is set up in Settings › AI, otherwise on Accnomos's own server). Lives only on
 * this device (localStorage) and goes to the runtime as `X-AI-Route` on every request once the user has chosen;
 * with nothing saved the header is left out and the runtime uses its default (Meta Model API first).
 * The Android app offers the same three options in the same words (apps/mobile/lib/services/ai_route.dart).
 */
export type AiRoute = "meta_first" | "local_first" | "local_only";

export const AI_ROUTE_KEY = "accnomos.ai.route";
export const AI_ROUTE_HEADER = "X-AI-Route";
export const DEFAULT_AI_ROUTE: AiRoute = "meta_first";

export interface AiRouteOption {
  value: AiRoute;
  label: string;
  badge?: string;
  description: string;
}

export const AI_ROUTE_OPTIONS: readonly AiRouteOption[] = [
  {
    value: "meta_first",
    label: "Meta Model API first",
    badge: "RECOMMENDED",
    description: "Best accuracy and voice. The local model takes over only if the Meta Model API is down.",
  },
  {
    value: "local_first",
    label: "Local model first, Meta API when unsure",
    description:
      "Saves Meta credits and keeps most of your data off the Meta Model API. When the local model's answer does not come back in a usable form, or the local model is down, the same request goes to the Meta Model API.",
  },
  {
    value: "local_only",
    label: "Local model only",
    description: "Nothing is sent to the Meta Model API.",
  },
];

export const AI_ROUTE_INTRO =
  "Muse Spark runs on the Meta Model API. The local model, Muse Glimmer 30B, runs on your own computer if you set one up above, otherwise on Accnomos's own server.";

export const LOCAL_ONLY_WARNING_TITLE = "What local only means";

export const LOCAL_ONLY_WARNINGS: readonly string[] = [
  "Slower: reading a receipt or invoice can take a minute or more.",
  "Less accurate on messy photos, handwriting and long PDFs, so more items are left for you to check.",
  "No voice input: speech-to-text (Muse Voice Transcribe) runs on the Meta Model API. You can still type, and replies can still be read out by your device.",
  "If the local model is offline, AI features wait; nothing falls back.",
  "Every number is still checked by code before anything is saved, whichever you pick.",
];

function isAiRoute(v: unknown): v is AiRoute {
  return v === "meta_first" || v === "local_first" || v === "local_only";
}

/** The saved choice, or null when the user has not picked one (or storage is unavailable). */
export function loadAiRoute(): AiRoute | null {
  try {
    const raw = window.localStorage.getItem(AI_ROUTE_KEY);
    return isAiRoute(raw) ? raw : null;
  } catch {
    return null;
  }
}

export function saveAiRoute(route: AiRoute): void {
  try {
    window.localStorage.setItem(AI_ROUTE_KEY, route);
  } catch {
    /* storage unavailable (private mode) — the choice lives for this page only */
  }
}

/** `X-AI-Route` when the user has saved a choice; empty otherwise, so the runtime keeps its default. */
export function aiRouteHeaders(): Record<string, string> {
  const route = loadAiRoute();
  return route ? { [AI_ROUTE_HEADER]: route } : {};
}
