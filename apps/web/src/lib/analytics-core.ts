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
const MAX_STRING = 40;
const MAX_KEYS = 8;

/** Keeps counts, durations, flags and short labels; drops forbidden keys, long strings and anything that looks like an email. */
export function cleanProps(props: Record<string, unknown> | undefined): TrackProps {
  const out: TrackProps = {};
  if (!props) return out;
  for (const [k, v] of Object.entries(props)) {
    if (Object.keys(out).length >= MAX_KEYS) break;
    if (FORBIDDEN_KEY.test(k)) continue;
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
    else if (typeof v === "boolean") out[k] = v;
    else if (typeof v === "string" && v.length <= MAX_STRING && !/@/.test(v)) out[k] = v;
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
    if (deps.optedOut() || !name) return;
    queue.push({ name: name.slice(0, 60), props: cleanProps(props), app: "web", version: deps.version });
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
