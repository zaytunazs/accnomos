"use client";

/**
 * "Meta models at work": who served each AI result (the runtime's provider chain, services/runtime/app/ai/chain.py),
 * the chain's live health (GET /ai/health) and the last AI calls (GET /ai/calls). No secrets come back from either.
 */
import { loadAiConfig, RUNTIME_URL } from "./ai-config";
import type { RtProposal, RtServedBy } from "./runtime";

const PROVIDERS: Record<string, string> = {
  modal: "Modal",
  meta: "Meta Model API",
  spark: "DGX Spark",
  baseten: "Baseten",
  local: "your machine",
  key: "your Meta key",
  test: "test stub",
  ollama: "your machine",
};

/** "Modal", "Meta Model API", "DGX Spark"... for a provider name the runtime records. */
export function providerLabel(name: string): string {
  return PROVIDERS[name] ?? name;
}

/** The Meta model's product name for a model id: "muse-glimmer:30b" -> "Muse Glimmer 30B". */
export function metaModelName(model: string): string {
  const m = model.trim().replace(/^meta-models\//, "");
  if (/stub/i.test(m)) return "Test stub";
  if (/^muse-glimmer:30b$/i.test(m)) return "Muse Glimmer 30B";
  if (/^muse-spark-open/i.test(m)) return "Muse Spark Open";
  if (/^muse-spark/i.test(m)) return "Muse Spark";
  return m || "a model";
}

const seconds = (ms: number) => `${ms < 10_000 ? (ms / 1000).toFixed(1) : Math.round(ms / 1000)} s`;

/** "Muse Glimmer 30B (Modal)" */
export function servedName(s: RtServedBy): string {
  if (s.provider === "test") return "the test stub";
  return `${metaModelName(s.model)} (${providerLabel(s.provider)})`;
}

/**
 * The Review card's line: "Read by Muse Glimmer 30B (Modal) · 14 s · checked by Muse Spark Open (Baseten)", plus
 * "· Modal did not answer" when a provider was skipped. Null when the runtime did not say (older proposals, samples).
 */
export function servedLine(p: Pick<RtProposal, "served_by" | "verification">): string | null {
  const s = p.served_by;
  if (!s) return null;
  const parts = [`Read by ${servedName(s)} · ${seconds(s.latency_ms)}`];
  const v = p.verification?.served_by;
  if (v) parts.push(`checked by ${servedName(v)}`);
  const fell = [...new Set([...s.fell_back_from, ...(v?.fell_back_from ?? [])])];
  if (fell.length) parts.push(`${fell.map(providerLabel).join(", ")} did not answer`);
  return parts.join(" · ");
}

export interface ProviderHealth {
  name: string;
  label: string;
  model: string;
  configured: boolean;
  vision: boolean;
  json_mode: boolean;
  voice: boolean;
  status: "up" | "warm" | "idle" | "down" | "not configured";
  detail: string;
  probe_ms: number | null;
  circuit: "open" | "closed";
  retry_in_s: number | null;
  last_ok_s_ago: number | null;
  last_error: string | null;
}

export interface AiHealth {
  chain: string[];
  configured: string[];
  providers: ProviderHealth[];
  checked_at: number;
  cached: boolean;
  unknown: string[];
}

export interface AiCall {
  at: string;
  task: string;
  provider: string;
  model: string;
  latency_ms: number;
  ok: boolean;
  fell_back_from: string[];
  error: string | null;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${RUNTIME_URL}${path}`);
  if (!res.ok) throw new Error(`GET ${path} returned ${res.status}`);
  return (await res.json()) as T;
}

export const aiHealth = () => getJson<AiHealth>("/ai/health");
export const aiCalls = () => getJson<AiCall[]>("/ai/calls");

/**
 * POST /ai/warm when this device uses the server's models (no AI of its own chosen), so a cold Modal container is
 * starting while the user looks at the page. Fire and forget; the runtime sends at most one ping a minute.
 */
export function warmServerAi(): void {
  try {
    if (loadAiConfig() !== null) return; // the user's own backend: nothing of ours to warm
    void fetch(`${RUNTIME_URL}/ai/warm`, { method: "POST" }).catch(() => undefined);
  } catch {
    /* no storage or no network: the first real call just waits for the cold start */
  }
}
