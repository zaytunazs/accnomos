/**
 * HTTP 402 {code:"plan_limit"}: parsing it, the friendly sentence, and telling the page's one dialog. Its own small
 * module because lib/runtime.ts calls it from every failed request, so it must stay out of the weight of billing.ts.
 */
import type { PlanCode } from "./billing";

const PLAN_CODES: string[] = ["starter", "comprehensive", "ultimate"];

// ---- HTTP 402 plan_limit ------------------------------------------------------------------------------------------

/** Fired on `window` when the runtime refuses an action at a plan limit (HTTP 402 {code:"plan_limit"}). */
export const PLAN_LIMIT_EVENT = "accnomos:plan-limit";

export interface PlanLimitInfo {
  code: "plan_limit";
  /** The runtime's own words, when it sends some. */
  message: string | null;
  /** Which limit: docs, ask, invoices, bank_feeds, users, marketplaces, payroll_employees, autopilot_rules, … */
  limit_key: string | null;
  plan_code: PlanCode | null;
}

/**
 * Reads a 402 body: `{code:"plan_limit", …}` or FastAPI's `{detail:{code:"plan_limit", …}}`. Null for anything else
 * (another 402, a body that is not JSON), so ordinary errors keep their usual path.
 */
export function parsePlanLimit(status: number, body: string): PlanLimitInfo | null {
  if (status !== 402) return null;
  let json: unknown;
  try {
    json = JSON.parse(body);
  } catch {
    return null;
  }
  const root = json && typeof json === "object" ? (json as Record<string, unknown>) : null;
  const inner = root && root.detail && typeof root.detail === "object" ? (root.detail as Record<string, unknown>) : root;
  if (!inner || inner.code !== "plan_limit") return null;
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  const plan = str(inner.plan_code);
  return {
    code: "plan_limit",
    message: str(inner.message),
    limit_key: str(inner.limit) ?? str(inner.limit_key) ?? str(inner.feature),
    plan_code: plan && PLAN_CODES.includes(plan) ? (plan as PlanCode) : null,
  };
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

/** The friendly sentence the dialog opens with. Never blames the user, never says anything is locked. */
export function planLimitMessage(info: PlanLimitInfo): string {
  const what = info.limit_key ? LIMIT_WORDS[info.limit_key] : undefined;
  const lead = what ? `You have reached this month's limit for ${what} on your plan.` : "You have reached a limit on your plan.";
  return `${lead} Nothing is lost: you can still approve, edit and export everything already in your books.`;
}

/** Top-up helps only documents; everything else is an upgrade. */
export const topUpHelps = (info: PlanLimitInfo): boolean => info.limit_key === null || info.limit_key === "docs";

/**
 * Called with every failed runtime response (lib/runtime.ts): when it is a plan limit, tells the page's dialog and
 * returns the info. `notify` is injectable for the unit tests; the default dispatches PLAN_LIMIT_EVENT on window.
 */
let lastLimit: PlanLimitInfo | null = null;
/** The limit that woke the dialog, for a dialog that was still loading when it fired (taken once). */
export function takeLastPlanLimit(): PlanLimitInfo | null {
  const l = lastLimit;
  lastLimit = null;
  return l;
}

export function handlePlanLimit(
  status: number,
  body: string,
  notify: (info: PlanLimitInfo) => void = (info) => {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(PLAN_LIMIT_EVENT, { detail: info }));
  },
): PlanLimitInfo | null {
  const info = parsePlanLimit(status, body);
  if (info) {
    lastLimit = info;
    notify(info);
  }
  return info;
}
