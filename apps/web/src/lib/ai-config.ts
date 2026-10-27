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
  // Same-tab listeners (the sidebar label) don't get a `storage` event.
  try {
    window.dispatchEvent(new CustomEvent<AiConfig>(AI_CONFIG_EVENT, { detail: cfg }));
  } catch {
    /* old browser — the label re-reads on its next render */
  }
}

/** Fired on `window` by [saveAiConfig] so same-tab readers follow the choice. */
export const AI_CONFIG_EVENT = "accnomos:ai-config";

/** Short human name for a model id the UI shows. */
export function shortModelName(model: string): string {
  const m = model.trim();
  if (/^muse-glimmer:30b$/i.test(m)) return "Glimmer 30B";
  if (/^muse-spark/i.test(m)) return "Muse Spark";
  return m || "a model";
}

/**
 * The sidebar line for the saved AI choice — the same store `ChooseAi`
 * writes, so the label always names the real setup: Glimmer on your machine,
 * Muse Spark on your key, or the stub the tests point at.
 */
export function aiLabel(cfg: AiConfig | null): string {
  if (cfg === null) return "AI: local Meta agent (Glimmer 30B)";
  if (/stub/i.test(cfg.model)) return "AI: stub answers (test mode)";
  if (cfg.mode === "key") return `AI: Muse Spark key (${cfg.model.trim() || "muse-spark-1.3"})`;
  return `AI: ${shortModelName(cfg.model)} on your machine`;
}

/** The last passing connection test, so Home's setup checklist can tell "chosen" from "tested". */
export interface AiTestRecord {
  ok: boolean;
  mode: AiMode;
  baseUrl: string;
  model: string;
  at: string;
}

const TEST_KEY = "accnomos.ai.test";

export function loadAiTest(): AiTestRecord | null {
  try {
    const raw = window.localStorage.getItem(TEST_KEY);
    return raw ? (JSON.parse(raw) as AiTestRecord) : null;
  } catch {
    return null;
  }
}

export function saveAiTest(cfg: AiConfig, ok: boolean): void {
  try {
    window.localStorage.setItem(
      TEST_KEY,
      JSON.stringify({ ok, mode: cfg.mode, baseUrl: cfg.baseUrl, model: cfg.model, at: new Date().toISOString() } satisfies AiTestRecord),
    );
  } catch {
    /* storage unavailable — the checklist treats AI as untested */
  }
}

/** True when the saved config answers: a passing test recorded for exactly this address and model. */
export function aiTested(cfg: AiConfig | null): boolean {
  if (!cfg) return false;
  const hasAddress = cfg.baseUrl.trim() !== "" && cfg.model.trim() !== "";
  const hasKey = cfg.mode !== "key" || (cfg.apiKey ?? "").trim() !== "";
  if (!hasAddress || !hasKey) return false;
  const test = loadAiTest();
  return test?.ok === true && test.mode === cfg.mode && test.baseUrl === cfg.baseUrl && test.model === cfg.model;
}

/** Headers the runtime reads (see services/runtime/app/ai/config.py). */
export function aiHeaders(cfg: AiConfig): Record<string, string> {
  const h: Record<string, string> = { "X-AI-Mode": cfg.mode, "X-AI-Base-Url": cfg.baseUrl, "X-AI-Model": cfg.model };
  if (cfg.mode === "key" && cfg.apiKey) h["X-Meta-Api-Key"] = cfg.apiKey;
  return h;
}

export const RUNTIME_URL = process.env.NEXT_PUBLIC_RUNTIME_URL ?? "http://localhost:8780";
/** Stateless HMRC relay (services/hmrc-relay); holds only the HMRC client secret. */
export const RELAY_URL = process.env.NEXT_PUBLIC_RELAY_URL ?? "http://localhost:8787";
