"use client";

/**
 * The user's AI connection (decision H14). Lives only on this device (localStorage) and is sent to the
 * stateless runtime as headers on each request; the runtime never stores it.
 */
export type AiMode = "local" | "key";

export interface AiConfig {
  mode: AiMode;
  baseUrl: string; // local: the user's agent (Ollama/runtime) URL · key: Meta Model API base
  model: string;
  apiKey?: string; // key mode only; never leaves the device except to the runtime over HTTPS
}

const KEY = "accnomos.ai";

export const DEFAULT_LOCAL: AiConfig = { mode: "local", baseUrl: "http://192.168.1.176:11434", model: "muse-glimmer:30b" };
export const DEFAULT_KEY: AiConfig = { mode: "key", baseUrl: "https://api.meta.ai/v1", model: "muse-spark-1.3", apiKey: "" };

export function loadAiConfig(): AiConfig | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as AiConfig) : null;
  } catch {
    return null;
  }
}

export function saveAiConfig(cfg: AiConfig): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(cfg));
  } catch {
    /* storage unavailable (private mode) — config lives for this page only */
  }
}

export function clearAiConfig(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Headers the runtime reads (see services/runtime/app/ai/config.py). */
export function aiHeaders(cfg: AiConfig): Record<string, string> {
  const h: Record<string, string> = { "X-AI-Mode": cfg.mode, "X-AI-Base-Url": cfg.baseUrl, "X-AI-Model": cfg.model };
  if (cfg.mode === "key" && cfg.apiKey) h["X-Meta-Api-Key"] = cfg.apiKey;
  return h;
}

export const RUNTIME_URL = process.env.NEXT_PUBLIC_RUNTIME_URL ?? "http://localhost:8780";
