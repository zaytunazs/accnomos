/**
 * Admin wire types and tolerant readers (docs/billing/PLANS_AND_CONTRACT.md, "Admin"). The contract names the data
 * and the tables but not every JSON key, so each reader accepts the obvious variants and never throws: a missing
 * number is 0, a missing list is empty. The shapes the UI expects are listed in docs/billing/ADMIN_UI_NOTES.md.
 * Pure: type-only imports, so the unit tests run it alone.
 */
import type { BillingInterval, BillingStatus, PlanCode, PlanLimits, RtPlan, RtUsage } from "./billing";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const pick = (o: Obj, ...keys: string[]): unknown => {
  for (const k of keys) if (o[k] !== undefined) return o[k];
  return undefined;
};

export interface AdminMetrics {
  signups: { day: string; count: number }[];
  trialing: number;
  active_by_plan: Record<string, number>;
  past_due: number;
  cancelled: number;
  mrr_pence: number;
  trials_ending_7d: number;
}

export function readMetrics(raw: unknown): AdminMetrics {
  const o = obj(raw);
  const s = pick(o, "signups", "signups_by_day", "signups_30d");
  const signups = Array.isArray(s)
    ? s.map((r) => ({ day: str(obj(r).day ?? obj(r).date), count: num(obj(r).count ?? obj(r).signups) }))
    : Object.entries(obj(s)).map(([day, count]) => ({ day, count: num(count) }));
  const active = obj(pick(o, "active_by_plan", "active"));
  return {
    signups: signups.sort((a, b) => a.day.localeCompare(b.day)),
    trialing: num(o.trialing),
    active_by_plan: Object.fromEntries(Object.entries(active).map(([k, v]) => [k, num(v)])),
    past_due: num(o.past_due),
    cancelled: num(o.cancelled),
    mrr_pence: num(pick(o, "mrr_pence", "mrr")),
    trials_ending_7d: num(pick(o, "trials_ending_7d", "trials_ending_in_7_days", "trials_ending")),
  };
}

export interface AdminUsage {
  docs: number;
  ask: number;
  invoices: number;
  topup_docs_remaining: number;
}

export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string | null;
  auth_kind: string;
  plan_code: PlanCode;
  status: BillingStatus;
  created_at: string | null;
  last_seen_at: string | null;
  trial_ends_at: string | null;
  comp_until: string | null;
  billing_interval: BillingInterval | null;
  country: string | null;
  usage: AdminUsage;
}

export function readUsage(raw: unknown): AdminUsage {
  const o = obj(raw);
  return { docs: num(o.docs), ask: num(o.ask), invoices: num(o.invoices), topup_docs_remaining: num(o.topup_docs_remaining) };
}

export function readUserRow(raw: unknown): AdminUserRow {
  const o = obj(raw);
  return {
    id: str(o.id),
    email: str(o.email),
    display_name: strOrNull(o.display_name),
    auth_kind: str(o.auth_kind),
    plan_code: (str(o.plan_code) || "comprehensive") as PlanCode,
    status: (str(o.status) || "trialing") as BillingStatus,
    created_at: strOrNull(o.created_at),
    last_seen_at: strOrNull(o.last_seen_at),
    trial_ends_at: strOrNull(o.trial_ends_at),
    comp_until: strOrNull(o.comp_until),
    billing_interval: (strOrNull(o.billing_interval) as BillingInterval | null) ?? null,
    country: strOrNull(o.country),
    usage: readUsage(pick(o, "usage", "usage_this_month")),
  };
}

export interface AdminUserList {
  items: AdminUserRow[];
  total: number;
  page: number;
  page_size: number;
}

export function readUserList(raw: unknown, page = 1): AdminUserList {
  const o = obj(raw);
  const rows = Array.isArray(raw) ? raw : arr(pick(o, "items", "users", "rows"));
  const items = rows.map(readUserRow);
  return { items, total: num(o.total) || items.length, page: num(o.page) || page, page_size: num(pick(o, "page_size", "per_page")) || 25 };
}

export interface AuditRow {
  id: string;
  at: string;
  admin_email: string;
  account_id: string | null;
  action: string;
  detail: Obj;
}

export function readAudit(raw: unknown): AuditRow {
  const o = obj(raw);
  return { id: str(o.id), at: str(o.at), admin_email: str(o.admin_email), account_id: strOrNull(o.account_id), action: str(o.action), detail: obj(o.detail) };
}

export function readAuditList(raw: unknown): AuditRow[] {
  const o = obj(raw);
  return (Array.isArray(raw) ? raw : arr(pick(o, "items", "rows", "audit"))).map(readAudit);
}

export interface StripeSummary {
  customer_id: string | null;
  subscription: { id: string; status: string; current_period_end: string | null; cancel_at_period_end: boolean } | null;
  invoices: { id: string; created: string; amount_pence: number; status: string; url: string | null }[];
}

export interface AdminUserDetail {
  account: AdminUserRow;
  notes: string;
  usage_history: (AdminUsage & { month: string })[];
  redemptions: { code: string; redeemed_at: string }[];
  stripe: StripeSummary | null;
  audit: AuditRow[];
}

export function readUserDetail(raw: unknown): AdminUserDetail {
  const o = obj(raw);
  const account = readUserRow(o.account ?? o);
  const st = o.stripe && typeof o.stripe === "object" ? obj(o.stripe) : null;
  const sub = st && st.subscription && typeof st.subscription === "object" ? obj(st.subscription) : null;
  return {
    account,
    notes: str(pick(o, "notes") ?? obj(o.account).notes),
    usage_history: arr(pick(o, "usage_history", "usage")).map((r) => ({ month: str(obj(r).month), ...readUsage(r) })),
    redemptions: arr(o.redemptions).map((r) => ({ code: str(obj(r).code), redeemed_at: str(obj(r).redeemed_at) })),
    stripe: st
      ? {
          customer_id: strOrNull(st.customer_id),
          subscription: sub
            ? { id: str(sub.id), status: str(sub.status), current_period_end: strOrNull(sub.current_period_end), cancel_at_period_end: sub.cancel_at_period_end === true }
            : null,
          invoices: arr(st.invoices).map((i) => ({
            id: str(obj(i).id),
            created: str(obj(i).created),
            amount_pence: num(obj(i).amount_pence),
            status: str(obj(i).status),
            url: strOrNull(obj(i).url),
          })),
        }
      : null,
    audit: arr(o.audit).map(readAudit),
  };
}

export type CodeKind = "percent" | "fixed" | "free_months";

export interface PromoCode {
  code: string;
  kind: CodeKind;
  /** percent (1-100), pence off, or months. */
  value: number;
  plan_codes: PlanCode[] | null;
  max_redemptions: number | null;
  redeemed_count: number;
  expires_at: string | null;
  active: boolean;
  created_by?: string | null;
  stripe_coupon_id?: string | null;
}

export function readCode(raw: unknown): PromoCode {
  const o = obj(raw);
  const plans = Array.isArray(o.plan_codes) ? (o.plan_codes as PlanCode[]) : null;
  return {
    code: str(o.code),
    kind: (str(o.kind) || "percent") as CodeKind,
    value: num(o.value),
    plan_codes: plans && plans.length ? plans : null,
    max_redemptions: typeof o.max_redemptions === "number" ? o.max_redemptions : null,
    redeemed_count: num(o.redeemed_count),
    expires_at: strOrNull(o.expires_at),
    active: o.active !== false,
    created_by: strOrNull(o.created_by),
    stripe_coupon_id: strOrNull(o.stripe_coupon_id),
  };
}

export const readCodes = (raw: unknown): PromoCode[] => (Array.isArray(raw) ? raw : arr(obj(raw).items ?? obj(raw).codes)).map(readCode);

/** What a code gives, in words. */
export function describeCode(c: Pick<PromoCode, "kind" | "value">): string {
  if (c.kind === "percent") return `${c.value}% off`;
  if (c.kind === "fixed") return `£${(c.value / 100).toFixed(2)} off`;
  return `${c.value} month${c.value === 1 ? "" : "s"} free`;
}

export interface AdminPlan extends RtPlan {
  active: boolean;
  sort?: number;
  stripe_price_month?: string | null;
  stripe_price_year?: string | null;
}

export function readPlan(raw: unknown): AdminPlan {
  const o = obj(raw);
  return {
    code: str(o.code) as PlanCode,
    name: str(o.name),
    price_month_pence: num(o.price_month_pence),
    price_year_pence: num(o.price_year_pence),
    limits: obj(o.limits) as PlanLimits,
    active: o.active !== false,
    sort: typeof o.sort === "number" ? o.sort : undefined,
    stripe_price_month: strOrNull(o.stripe_price_month),
    stripe_price_year: strOrNull(o.stripe_price_year),
  };
}

export const readPlans = (raw: unknown): AdminPlan[] => (Array.isArray(raw) ? raw : arr(obj(raw).items ?? obj(raw).plans)).map(readPlan);

export interface AdminAnalytics {
  daily_active: { day: string; count: number }[];
  funnel: { signed_up: number; first_document: number; first_approval: number };
  features: Record<string, number>;
  conversion: { trials: number; converted: number; rate: number };
  churn: { cancelled: number; rate: number };
  errors: { route: string; count: number }[];
}

export function readAnalytics(raw: unknown): AdminAnalytics {
  const o = obj(raw);
  const f = obj(pick(o, "funnel"));
  const c = obj(pick(o, "conversion"));
  const ch = obj(pick(o, "churn"));
  const dau = pick(o, "daily_active", "dau", "daily_active_accounts");
  return {
    daily_active: arr(dau).map((r) => ({ day: str(obj(r).day ?? obj(r).date), count: num(obj(r).count ?? obj(r).active) })),
    funnel: { signed_up: num(pick(f, "signed_up", "signups")), first_document: num(pick(f, "first_document", "first_doc")), first_approval: num(pick(f, "first_approval", "first_approved")) },
    features: Object.fromEntries(Object.entries(obj(pick(o, "features", "feature_use"))).map(([k, v]) => [k, num(v)])),
    conversion: { trials: num(pick(c, "trials", "trials_started")), converted: num(pick(c, "converted", "paid")), rate: num(pick(c, "rate")) },
    churn: { cancelled: num(pick(ch, "cancelled", "count")), rate: num(pick(ch, "rate")) },
    errors: arr(pick(o, "errors", "top_errors")).map((r) => ({ route: str(obj(r).route), count: num(obj(r).count) })),
  };
}

export type BugStatus = "new" | "triaged" | "fixed" | "wont_fix";
export const BUG_STATUSES: BugStatus[] = ["new", "triaged", "fixed", "wont_fix"];
export const BUG_LABEL: Record<BugStatus, string> = { new: "New", triaged: "Triaged", fixed: "Fixed", wont_fix: "Won't fix" };

export interface BugReport {
  id: string;
  at: string;
  account_id: string | null;
  email: string | null;
  message: string;
  page: string;
  app: string;
  version: string;
  ua: string;
  screenshot_path: string | null;
  /** Not in the first contract: the screenshot as a data URL, when the admin API returns it inline. */
  screenshot_b64?: string | null;
  status: BugStatus;
  admin_notes: string;
}

export function readBug(raw: unknown): BugReport {
  const o = obj(raw);
  return {
    id: str(o.id),
    at: str(o.at),
    account_id: strOrNull(o.account_id),
    email: strOrNull(o.email),
    message: str(o.message),
    page: str(o.page),
    app: str(o.app),
    version: str(o.version),
    ua: str(o.ua),
    screenshot_path: strOrNull(o.screenshot_path),
    screenshot_b64: strOrNull(o.screenshot_b64),
    status: (str(o.status) || "new") as BugStatus,
    admin_notes: str(o.admin_notes),
  };
}

export const readBugs = (raw: unknown): BugReport[] => (Array.isArray(raw) ? raw : arr(obj(raw).items ?? obj(raw).rows)).map(readBug);

/** Account fields the admin can set with PATCH /admin/users/{id}. */
export interface AdminUserPatch {
  plan_code?: PlanCode;
  trial_ends_at?: string | null;
  comp_until?: string | null;
  status?: BillingStatus;
  notes?: string;
}

export type AdminAction =
  | { action: "extend_trial"; days: number }
  | { action: "apply_code"; code: string }
  | { action: "cancel_at_period_end" }
  | { action: "resume" }
  | { action: "send_portal_link" }
  | { action: "grant_topup"; docs: number };

export type { RtUsage };
