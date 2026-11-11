/**
 * HTTP 402 from the runtime: parsing it, the friendly sentence, and telling the page's one dialog. Its own small module
 * because lib/runtime.ts calls it from every failed request, so it must stay out of the weight of billing.ts.
 *
 * Two bodies (services/runtime/app/billing/service.py, `PlanLimit.body` and `ReadOnly.body`):
 *   {code: "plan_limit", counter, limit, used, upgrade_url, detail}  an allowance is used up
 *   {code: "read_only", status, upgrade_url, detail}                 the trial ended or the plan was cancelled
 */

// ---- HTTP 402 ----------------------------------------------------------------------------------------------------

/** Fired on `window` when the runtime refuses an action with HTTP 402 (`detail` is a BillingRefusal). */
export const PLAN_LIMIT_EVENT = "accnomos:plan-limit";

/** 402 `plan_limit`: one more of `counter` would pass the plan's `limit` (`used` so far). */
export interface PlanLimitBody {
  code: "plan_limit";
  /** docs, ask, invoices, bank_feeds, users, marketplaces, payroll_employees, autopilot_rules */
  counter: string | null;
  limit: number | null;
  used: number | null;
  upgrade_url: string | null;
  /** The runtime's own sentence. */
  detail: string | null;
}

/** 402 `read_only`: the account can view and export but not add or change anything until a plan is chosen. */
export interface ReadOnlyBody {
  code: "read_only";
  /** trial_ended or cancelled */
  status: string | null;
  upgrade_url: string | null;
  detail: string | null;
}

export type BillingRefusal = PlanLimitBody | ReadOnlyBody;
/** Kept for the callers that only care about the plan limit case. */
export type PlanLimitInfo = PlanLimitBody;

const MONTHLY = new Set(["docs", "ask", "invoices"]);

/**
 * Reads a 402 body, top level or under FastAPI's `detail` object. Null for anything else (another status, another
 * code, a body that is not JSON), so ordinary errors keep their usual path.
 */
export function parseBillingRefusal(status: number, body: string): BillingRefusal | null {
  if (status !== 402) return null;
  let json: unknown;
  try {
    json = JSON.parse(body);
  } catch {
    return null;
  }
  const root = json && typeof json === "object" && !Array.isArray(json) ? (json as Record<string, unknown>) : null;
  const inner = root && root.detail && typeof root.detail === "object" ? (root.detail as Record<string, unknown>) : root;
  if (!inner) return null;
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  if (inner.code === "plan_limit") {
    return { code: "plan_limit", counter: str(inner.counter), limit: num(inner.limit), used: num(inner.used), upgrade_url: str(inner.upgrade_url), detail: str(inner.detail) };
  }
  if (inner.code === "read_only") {
    return { code: "read_only", status: str(inner.status), upgrade_url: str(inner.upgrade_url), detail: str(inner.detail) };
  }
  return null;
}

/** Only the `plan_limit` case (null for read-only and everything else). */
export function parsePlanLimit(status: number, body: string): PlanLimitBody | null {
  const r = parseBillingRefusal(status, body);
  return r && r.code === "plan_limit" ? r : null;
}

const LIMIT_WORDS: Record<string, string> = {
  docs: "AI-read documents",
  ask: "Ask questions",
  invoices: "sales invoices and quotes",
  bank_feeds: "live bank feeds",
  users: "users",
  marketplaces: "marketplace connections",
  payroll_employees: "payroll employees",
  autopilot_rules: "Autopilot rules",
};

const NOTHING_LOST = "Nothing is lost: you can still approve, edit and export everything already in your books.";

/** The dialog's title. */
export function refusalTitle(info: BillingRefusal): string {
  if (info.code === "read_only") return info.status === "cancelled" ? "Your plan has been cancelled" : "Your free trial has ended";
  return "You have reached your plan's limit";
}

/** The friendly sentence the dialog opens with. Never blames the user, never says anything is locked away. */
export function planLimitMessage(info: BillingRefusal): string {
  if (info.code === "read_only") {
    const why = info.status === "cancelled" ? "Your plan has been cancelled" : "Your free trial has ended";
    return `${why}, so your books are read-only. Everything is still there: you can view and export it.`;
  }
  const what = info.counter ? LIMIT_WORDS[info.counter] : undefined;
  if (!what) return `You have reached a limit on your plan. ${NOTHING_LOST}`;
  if (info.limit === 0) return `Your plan does not include ${what}. ${NOTHING_LOST}`;
  const n = info.limit !== null ? `all ${info.limit.toLocaleString("en-GB")} of ` : "all of ";
  const lead = info.counter && MONTHLY.has(info.counter)
    ? `You have used ${n}this month's ${what} on your plan.`
    : `Your plan allows ${info.limit !== null ? info.limit.toLocaleString("en-GB") : "a set number of"} ${what}, and that many are already set up.`;
  return `${lead} ${NOTHING_LOST}`;
}

/** A top-up helps only documents; everything else is an upgrade (and read-only needs a plan). */
export const topUpHelps = (info: BillingRefusal): boolean => info.code === "plan_limit" && (info.counter === null || info.counter === "docs");

/**
 * Called with every failed runtime response (lib/runtime.ts): when it is a 402 plan limit or read-only refusal, tells
 * the page's dialog and returns it. `notify` is injectable for the unit tests; the default dispatches PLAN_LIMIT_EVENT.
 */
let lastLimit: BillingRefusal | null = null;
/**
 * The refusal the dialog should show: kept until the dialog is closed (dismissPlanLimit), so a dialog that loads after
 * the event fired, or mounts again, still shows it.
 */
export const currentPlanLimit = (): BillingRefusal | null => lastLimit;

/** The dialog was closed. */
export function dismissPlanLimit(): void {
  lastLimit = null;
}

export function handlePlanLimit(
  status: number,
  body: string,
  notify: (info: BillingRefusal) => void = (info) => {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(PLAN_LIMIT_EVENT, { detail: info }));
  },
): BillingRefusal | null {
  const info = parseBillingRefusal(status, body);
  if (info) {
    lastLimit = info;
    notify(info);
  }
  return info;
}
