/**
 * Plans, limits and billing helpers (docs/billing/PLANS_AND_CONTRACT.md). Pure: no imports but types, so the unit
 * tests (tests/unit) run it on its own and the pricing page, Plan & billing and the 402 dialog share one source.
 * Prices are pence, ex VAT; UK VAT (20 %) is added at checkout and shown beside them.
 */

export type PlanCode = "starter" | "comprehensive" | "ultimate";
export type BillingStatus = "trialing" | "active" | "past_due" | "trial_ended" | "cancelled" | "comped";
export type BillingInterval = "month" | "year";

/** One limit: a number, null for unlimited, true/false for included/not included, text for a service level. */
export type LimitValue = number | boolean | string | null;
export type PlanLimits = Record<string, LimitValue | undefined>;

export const PLAN_CODES: PlanCode[] = ["starter", "comprehensive", "ultimate"];
export const VAT_RATE = 0.2;
export const TRIAL_DAYS = 90;
export const TRIAL_REMINDER_DAYS = 14;
export const TOPUP_DOCS = 100;
export const TOPUP_PENCE = 300;

/** What GET /plans returns for one plan. */
export interface RtPlan {
  code: PlanCode;
  name: string;
  price_month_pence: number;
  price_year_pence: number;
  limits: PlanLimits;
}

/** What GET /account returns for this month's use. */
export interface RtUsage {
  docs: number;
  ask: number;
  invoices: number;
  bank_feeds: number;
  users: number;
  marketplaces: number;
  topup_docs_remaining: number;
}

export interface RtAccount {
  id: string;
  email: string;
  plan_code: PlanCode;
  status: BillingStatus;
  trial_ends_at: string | null;
  comp_until: string | null;
  billing_interval: BillingInterval | null;
  usage: RtUsage;
  limits: PlanLimits;
  own_ai: boolean;
  /** Not in the first contract: GET /account reports the opt-out so the toggle can show it (see docs/billing/ADMIN_UI_NOTES.md). */
  analytics_opt_out?: boolean;
}

/** The plans as the contract sets them, used until (and if) GET /plans answers: a signed-out visitor sees prices at once. */
export const DEFAULT_PLANS: RtPlan[] = [
  {
    code: "starter",
    name: "Starter",
    price_month_pence: 1000,
    price_year_pence: 10000,
    limits: { users: 1, docs: 50, ask: 100, bank_feeds: 1, invoices: 20, marketplaces: 0, payroll_employees: 0, autopilot_rules: 5, multicurrency: false, support: "Email" },
  },
  {
    code: "comprehensive",
    name: "Comprehensive",
    price_month_pence: 2000,
    price_year_pence: 20000,
    limits: { users: 3, docs: 300, ask: 500, bank_feeds: 3, invoices: null, marketplaces: 1, payroll_employees: 3, autopilot_rules: null, multicurrency: false, support: "Email" },
  },
  {
    code: "ultimate",
    name: "Ultimate",
    price_month_pence: 5000,
    price_year_pence: 50000,
    limits: { users: 10, docs: 1500, ask: 3000, bank_feeds: null, invoices: null, marketplaces: null, payroll_employees: 20, autopilot_rules: null, multicurrency: true, support: "Priority email" },
  },
];

export const WHO_FOR: Record<PlanCode, string> = {
  starter: "Sole traders, side businesses",
  comprehensive: "VAT-registered sole traders, small companies",
  ultimate: "Busier companies, online sellers, teams",
};

/** A row of the limits table. `key` is the limit's name in `limits` (null: the same on every plan, `all` says what). */
export interface LimitRow {
  key: string | null;
  label: string;
  note?: string;
  /** Rows that do not come from `limits`: the same for each plan. */
  all?: LimitValue;
}

export const LIMIT_ROWS: LimitRow[] = [
  { key: "users", label: "Users", note: "Accountant access is free and extra" },
  { key: "docs", label: "AI-read documents", note: "Receipts, bills, statements, each month" },
  { key: "ask", label: "Ask questions", note: "Each month; fair use on Ultimate" },
  { key: "bank_feeds", label: "Live bank feeds" },
  { key: "invoices", label: "Sales invoices and quotes", note: "Each month" },
  { key: "marketplaces", label: "Marketplace connections", note: "eBay" },
  { key: null, label: "VAT returns", note: "Prepare and export; filing to HMRC follows HMRC's approval of our production access", all: true },
  { key: null, label: "Income Tax: Self Assessment and quarterly figures", all: true },
  { key: "payroll_employees", label: "Payroll (employees)", note: "Up to" },
  { key: "autopilot_rules", label: "Autopilot rules" },
  { key: "multicurrency", label: "Multi-currency, projects and job costing" },
  { key: "support", label: "Support" },
];

/** The text in one cell of the limits table. */
export function formatLimit(v: LimitValue | undefined, opts: { upTo?: boolean } = {}): string {
  if (v === null) return "Unlimited";
  if (v === undefined || v === false || v === 0) return "—";
  if (v === true) return "Included";
  if (typeof v === "number") return `${opts.upTo ? "Up to " : ""}${v.toLocaleString("en-GB")}`;
  return v;
}

/** Whether a limit means "no cap": null, or a negative number. */
export const isUnlimited = (v: LimitValue | undefined): boolean => v === null || (typeof v === "number" && v < 0);

/** A row's value for a plan: the live plan from GET /plans when it has the key, else the contract's table. */
export function limitFor(row: LimitRow, code: PlanCode, plans: RtPlan[] = DEFAULT_PLANS): LimitValue | undefined {
  if (row.key === null) return row.all;
  const live = plans.find((p) => p.code === code)?.limits;
  if (live && row.key in live) return live[row.key];
  return DEFAULT_PLANS.find((p) => p.code === code)?.limits[row.key];
}

export const limitCell = (row: LimitRow, code: PlanCode, plans?: RtPlan[]): string =>
  formatLimit(limitFor(row, code, plans), { upTo: row.key === "payroll_employees" });

/** £10, £8.33, £0.30: whole pounds without pence. */
export function money(pence: number): string {
  const pounds = pence / 100;
  return `£${Number.isInteger(pounds) ? pounds.toLocaleString("en-GB") : pounds.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** The inc-VAT figure of an ex-VAT price, to the penny. */
export const withVat = (pence: number): number => Math.round(pence * (1 + VAT_RATE));

/** Months paid for in a year when annual billing gives 2 months free: price_year = 10 × price_month. */
export function annualSaving(plan: Pick<RtPlan, "price_month_pence" | "price_year_pence">): number {
  return plan.price_month_pence * 12 - plan.price_year_pence;
}

/** What a plan costs per month on the chosen interval (annual: a twelfth of the year). */
export const perMonth = (plan: RtPlan, interval: BillingInterval): number =>
  interval === "month" ? plan.price_month_pence : Math.round(plan.price_year_pence / 12);

export const PLAN_NAMES: Record<PlanCode, string> = { starter: "Starter", comprehensive: "Comprehensive", ultimate: "Ultimate" };

export const STATUS_LABEL: Record<BillingStatus, string> = {
  trialing: "Free trial",
  active: "Active",
  past_due: "Payment overdue",
  trial_ended: "Trial ended",
  cancelled: "Cancelled",
  comped: "Free access",
};

/** Whole days from `now` to an ISO date or time (rounded up; 0 once it has passed). */
export function daysUntil(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.ceil((t - now.getTime()) / 86_400_000));
}

/** The reminder banner: shown while trialing in the last 14 days (and on the day itself). */
export function trialReminder(a: Pick<RtAccount, "status" | "trial_ends_at">, now: Date = new Date()): { days: number } | null {
  if (a.status !== "trialing") return null;
  const days = daysUntil(a.trial_ends_at, now);
  return days !== null && days <= TRIAL_REMINDER_DAYS ? { days } : null;
}

export interface Meter {
  key: string;
  label: string;
  used: number;
  /** null: no cap. */
  limit: number | null;
  /** 0 to 1 (1 when over); 0 when there is no cap. */
  ratio: number;
  state: "ok" | "near" | "full";
  extra?: string;
}

const METERS: { key: keyof RtUsage; label: string }[] = [
  { key: "docs", label: "AI-read documents" },
  { key: "ask", label: "Ask questions" },
  { key: "invoices", label: "Sales invoices and quotes" },
  { key: "bank_feeds", label: "Live bank feeds" },
  { key: "users", label: "Users" },
  { key: "marketplaces", label: "Marketplace connections" },
];

/** Usage against limits for the meters. Rows the plan does not include (limit 0) are left out unless something is used. */
export function usageMeters(a: Pick<RtAccount, "usage" | "limits" | "own_ai">): Meter[] {
  const out: Meter[] = [];
  for (const m of METERS) {
    const used = a.usage[m.key] ?? 0;
    const raw = a.limits[m.key];
    const unlimited = isUnlimited(raw) || ((m.key === "docs" || m.key === "ask") && a.own_ai);
    const limit = unlimited ? null : typeof raw === "number" ? raw : 0;
    if (limit === 0 && used === 0) continue;
    const ratio = limit ? Math.min(1, used / limit) : 0;
    const extra =
      m.key === "docs" && a.usage.topup_docs_remaining > 0
        ? `${a.usage.topup_docs_remaining.toLocaleString("en-GB")} top-up documents left`
        : m.key === "docs" && a.own_ai
          ? "Your own AI: fair use, no monthly cap"
          : undefined;
    out.push({ key: m.key, label: m.label, used, limit, ratio, state: ratio >= 1 ? "full" : ratio >= 0.8 ? "near" : "ok", extra });
  }
  return out;
}

/** "30 Jan 2027" */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/London" });
}
