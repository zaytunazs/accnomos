"use client";

/**
 * "AI models at work": who served each AI result (the runtime's provider chain, services/runtime/app/ai/chain.py),
 * the chain's live health (GET /ai/health) and the last AI calls (GET /ai/calls). No secrets come back from either.
 * Models are shown by what they are ("Local open-weights model", "Hosted model"), never by a vendor or product name.
 */
import { loadAiConfig, RUNTIME_URL } from "./ai-config";
import type { RtProposal, RtServedBy } from "./runtime";

const PROVIDERS: Record<string, string> = {
  modal: "hosted GPU",
  meta: "hosted model API",
  spark: "our own server",
  baseten: "hosted open weights",
  anthropic: "backup provider",
  local: "your machine",
  key: "your own API key",
  test: "test stub",
  ollama: "your machine",
};

/** "hosted GPU", "hosted model API", "our own server"... for a provider name the runtime records. */
export function providerLabel(name: string): string {
  return PROVIDERS[name] ?? name;
}

/** A neutral name for a model id: "muse-glimmer:30b" -> "Local open-weights model". No raw id reaches the screen. */
export function metaModelName(model: string): string {
  const m = model
    .trim()
    .replace(/^(meta|ollama|baseten|modal|spark|local|key|test|anthropic):/i, "")
    .replace(/^meta-models\//, "");
  if (/stub/i.test(m)) return "Test stub";
  if (/^(muse-)?glimmer/i.test(m)) return "Local open-weights model";
  if (/^muse-spark-open/i.test(m)) return "Open-weights verifier model";
  if (/^muse-spark/i.test(m)) return "Hosted model";
  if (/^claude/i.test(m)) return "Backup model";
  return m ? "AI model" : "a model";
}

const seconds = (ms: number) => `${ms < 10_000 ? (ms / 1000).toFixed(1) : Math.round(ms / 1000)} s`;

/** "the local open-weights model (hosted GPU)" */
export function servedName(s: RtServedBy): string {
  if (s.provider === "test") return "the test stub";
  const name = metaModelName(s.model);
  const shown = name === "a model" || name === "Test stub" ? name : `the ${name.charAt(0).toLowerCase()}${name.slice(1)}`;
  return `${shown} (${providerLabel(s.provider)})`;
}

/**
 * The Review card's line: "Read by the local open-weights model (hosted GPU) · 14 s · checked by the open-weights verifier model
 * (hosted open weights)", plus
 * "· hosted GPU did not answer" when a provider was skipped. Null when the runtime did not say (older proposals, samples).
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
 * POST /ai/warm when this device uses the server's models (no AI of its own chosen), so a cold hosted GPU container is
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
