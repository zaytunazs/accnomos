/**
 * First-party product analytics, the part with no browser or network in it (the unit tests run it on its own).
 * Events are batched, carry only a name and a few non-financial properties, and are dropped while the user has
 * opted out. No cookies, no ids of its own, no third party (docs/billing/PLANS_AND_CONTRACT.md).
 */

export type TrackProps = Record<string, string | number | boolean>;

export interface TrackEvent {
  name: string;
  props: TrackProps;
  app: "web";
  version: string;
}

/** POST /events {events: [...]}: what the runtime kept and what its rules (or an opt-out) dropped. */
export interface EventsResult {
  accepted: number;
  dropped: number;
}

export interface TrackerDeps {
  /** Sends one batch; resolves true when the server took it. */
  send: (events: TrackEvent[]) => Promise<boolean>;
  optedOut: () => boolean;
  version: string;
  /** Flush when this many events wait (default 10). */
  maxBatch?: number;
  /** Flush this long after the first waiting event (default 4 s). */
  delayMs?: number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (t: unknown) => void;
}

/** Property names that must never leave the device (amounts, people, files, tokens), whatever the caller passes. */
const FORBIDDEN_KEY = /amount|total|price|gross|net|vat|email|name|supplier|customer|file|text|token|secret|password|iban|sort|account/i;
const MAX_KEYS = 10;

const PAGE = /^\/[a-z0-9/_-]{0,99}$/;
const SLUG = /^[a-z0-9][a-z0-9_-]{0,39}$/;
const int = (lo: number, hi: number) => (v: unknown) => typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
const slug = (v: unknown) => typeof v === "string" && SLUG.test(v);
const page = (v: unknown) => typeof v === "string" && PAGE.test(v);
const bool = (v: unknown) => typeof v === "boolean";

/**
 * The properties the runtime accepts and what each may hold (services/runtime/app/billing/analytics.py PROP_RULES): a
 * key or value outside these is dropped here, so a batch never carries an event the runtime would refuse.
 */
export const PROP_RULES: Record<string, (v: unknown) => boolean> = {
  page,
  from_page: page,
  feature: slug,
  action: slug,
  step: slug,
  source: slug,
  result: slug,
  variant: slug,
  screen: slug,
  plan: (v) => v === "starter" || v === "comprehensive" || v === "ultimate",
  interval: (v) => v === "month" || v === "year",
  count: int(0, 100_000),
  duration_ms: int(0, 86_400_000),
  step_index: int(0, 100),
  ok: bool,
  own_ai: bool,
};

/** Event names the runtime records itself; a client may not send them (analytics.py SERVER_ONLY). */
export const SERVER_ONLY = new Set([
  "signup", "document_scanned", "proposal_approved", "bank_synced", "ask", "vat_export", "itsa_export", "ebay_sync", "checkout_started",
  "subscription_active", "subscription_cancelled", "trial_ended", "topup_bought", "code_redeemed", "api_error",
]);
const NAME = /^[a-z][a-z0-9_]{1,47}$/;

/** Whether the runtime takes an event of this name from a client. */
export const eventNameAllowed = (name: string): boolean => NAME.test(name) && !SERVER_ONLY.has(name);

/** Keeps the properties the runtime allows, with values it accepts; drops the rest (and anything that names money, people or files). */
export function cleanProps(props: Record<string, unknown> | undefined): TrackProps {
  const out: TrackProps = {};
  if (!props) return out;
  for (const [k, v] of Object.entries(props)) {
    if (Object.keys(out).length >= MAX_KEYS) break;
    if (FORBIDDEN_KEY.test(k)) continue;
    const rule = PROP_RULES[k];
    if (rule && rule(v)) out[k] = v as string | number | boolean;
  }
  return out;
}

export function createTracker(deps: TrackerDeps) {
  const maxBatch = deps.maxBatch ?? 10;
  const delayMs = deps.delayMs ?? 4000;
  const setTimer = deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = deps.clearTimer ?? ((t) => clearTimeout(t as ReturnType<typeof setTimeout>));
  let queue: TrackEvent[] = [];
  let timer: unknown = null;

  async function flush(): Promise<void> {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
    if (queue.length === 0) return;
    const batch = queue;
    queue = [];
    if (deps.optedOut()) return;
    try {
      await deps.send(batch);
    } catch {
      /* analytics never disturbs the page, and a lost batch is not retried */
    }
  }

  function track(name: string, props?: Record<string, unknown>): void {
    if (deps.optedOut() || !eventNameAllowed(name)) return;
    queue.push({ name, props: cleanProps(props), app: "web", version: deps.version });
    if (queue.length >= maxBatch) void flush();
    else if (timer === null) timer = setTimer(() => void flush(), delayMs);
  }

  /** Throw away what waits (the user has just opted out). */
  function discard(): void {
    queue = [];
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }

  return { track, flush, discard, pending: () => queue.length };
}
