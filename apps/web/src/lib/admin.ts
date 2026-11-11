/**
 * Admin wire types and readers (services/runtime/app/billing/admin.py). The types are the runtime's JSON exactly; the
 * keys are pinned in docs/billing/api_shapes.json, which tests/unit/api-shapes.test.ts checks these types and readers
 * against (and services/runtime/tests/test_billing_contract.py checks the runtime against), so drift fails CI.
 * The readers never throw: a missing number is 0, a missing list is empty, a missing text is "" or null.
 * Pure: type-only imports, so the unit tests run it alone.
 */
import type { BillingInterval, BillingStatus, PlanCode, PlanLimits, RtPlan } from "./billing";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const id = (v: unknown): string => (typeof v === "number" ? String(v) : str(v));

/** A Stripe time (seconds since 1970) as an ISO string, for longDate. */
export const fromUnix = (s: number | null | undefined): string | null => (typeof s === "number" && s > 0 ? new Date(s * 1000).toISOString() : null);

export interface DayCount {
  day: string;
  count: number;
}
const readDays = (v: unknown): DayCount[] => arr(v).map((r) => ({ day: str(obj(r).day), count: num(obj(r).count) }));

/** The admin's paged lists: users, audit, bug reports. */
export interface Paged<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
}
function readPaged<T>(raw: unknown, read: (r: unknown) => T): Paged<T> {
  const o = obj(raw);
  const items = arr(o.items).map(read);
  return { items, page: num(o.page) || 1, per_page: num(o.per_page) || 25, total: num(o.total) || items.length };
}

// ---- GET /admin/metrics --------------------------------------------------------------------------------------------

export interface AdminMetrics {
  signups_by_day: DayCount[];
  total_accounts: number;
  trialing: number;
  active_by_plan: Record<PlanCode, number>;
  active: number;
  past_due: number;
  cancelled: number;
  trial_ended: number;
  comped: number;
  mrr_pence: number;
  trials_ending_7d: number;
  trials_ending: { id: string; email: string; trial_ends_at: string }[];
}

export function readMetrics(raw: unknown): AdminMetrics {
  const o = obj(raw);
  const plans = obj(o.active_by_plan);
  return {
    signups_by_day: readDays(o.signups_by_day).sort((a, b) => a.day.localeCompare(b.day)),
    total_accounts: num(o.total_accounts),
    trialing: num(o.trialing),
    active_by_plan: { starter: num(plans.starter), comprehensive: num(plans.comprehensive), ultimate: num(plans.ultimate) },
    active: num(o.active),
    past_due: num(o.past_due),
    cancelled: num(o.cancelled),
    trial_ended: num(o.trial_ended),
    comped: num(o.comped),
    mrr_pence: num(o.mrr_pence),
    trials_ending_7d: num(o.trials_ending_7d),
    trials_ending: arr(o.trials_ending).map((r) => ({ id: str(obj(r).id), email: str(obj(r).email), trial_ends_at: str(obj(r).trial_ends_at) })),
  };
}

// ---- accounts ------------------------------------------------------------------------------------------------------

/** An `accounts` row as the admin API returns it (PATCH /admin/users/{id}, an action's `account`, the detail's `account`). */
export interface AdminAccount {
  id: string;
  email: string;
  display_name: string | null;
  auth_kind: string;
  auth_subject: string;
  created_at: string | null;
  last_seen_at: string | null;
  plan_code: PlanCode;
  status: BillingStatus;
  trial_ends_at: string | null;
  comp_until: string | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  billing_interval: BillingInterval | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  country: string | null;
  notes: string | null;
  analytics_opt_out: boolean;
}

/** This month's counts on a GET /admin/users row. */
export interface AdminUsage {
  docs: number;
  ask: number;
  invoices: number;
  topup_docs_remaining: number;
}

export interface AdminUserRow extends AdminAccount {
  usage: AdminUsage;
}

export function readUsage(raw: unknown): AdminUsage {
  const o = obj(raw);
  return { docs: num(o.docs), ask: num(o.ask), invoices: num(o.invoices), topup_docs_remaining: num(o.topup_docs_remaining) };
}

export function readAccount(raw: unknown): AdminAccount {
  const o = obj(raw);
  return {
    id: str(o.id),
    email: str(o.email),
    display_name: strOrNull(o.display_name),
    auth_kind: str(o.auth_kind),
    auth_subject: str(o.auth_subject),
    created_at: strOrNull(o.created_at),
    last_seen_at: strOrNull(o.last_seen_at),
    plan_code: (str(o.plan_code) || "comprehensive") as PlanCode,
    status: (str(o.status) || "trialing") as BillingStatus,
    trial_ends_at: strOrNull(o.trial_ends_at),
    comp_until: strOrNull(o.comp_until),
    stripe_customer_id: strOrNull(o.stripe_customer_id),
    stripe_subscription_id: strOrNull(o.stripe_subscription_id),
    billing_interval: strOrNull(o.billing_interval) as BillingInterval | null,
    current_period_end: strOrNull(o.current_period_end),
    cancel_at_period_end: o.cancel_at_period_end === true,
    country: strOrNull(o.country),
    notes: strOrNull(o.notes),
    analytics_opt_out: o.analytics_opt_out === true,
  };
}

export const readUserRow = (raw: unknown): AdminUserRow => ({ ...readAccount(raw), usage: readUsage(obj(raw).usage) });

/** GET /admin/users?q=&plan=&status=&page= */
export const readUserList = (raw: unknown): Paged<AdminUserRow> => readPaged(raw, readUserRow);

// ---- audit ---------------------------------------------------------------------------------------------------------

export interface AuditRow {
  /** A number from the database; kept as text here. */
  id: string;
  at: string;
  admin_email: string;
  account_id: string | null;
  action: string;
  /** What changed: free-form, different for each action. */
  detail: Obj;
}

export function readAudit(raw: unknown): AuditRow {
  const o = obj(raw);
  return { id: id(o.id), at: str(o.at), admin_email: str(o.admin_email), account_id: strOrNull(o.account_id), action: str(o.action), detail: obj(o.detail) };
}

/** GET /admin/audit?account_id=&page= */
export const readAuditList = (raw: unknown): Paged<AuditRow> => readPaged(raw, readAudit);

// ---- GET /admin/users/{id} -----------------------------------------------------------------------------------------

export interface StripeSubscription {
  id: string;
  status: string;
  cancel_at_period_end: boolean;
  /** Seconds since 1970 (Stripe's time), or null. */
  current_period_end: number | null;
  trial_end: number | null;
}

export interface StripeInvoice {
  id: string;
  number: string | null;
  status: string;
  /** Pence (Stripe's smallest unit), VAT included. */
  total: number;
  currency: string;
  /** Seconds since 1970. */
  created: number;
  hosted_invoice_url: string | null;
}

export interface StripeSummary {
  customer: string;
  subscription: StripeSubscription | null;
  invoices: StripeInvoice[];
  /** Only when Stripe refused or could not be reached: what it said. */
  error?: string;
}

export interface UsageMonth extends AdminUsage {
  account_id: string;
  /** The 1st of the month, YYYY-MM-DD. */
  month: string;
  topup_expires_at: string | null;
}

export interface Redemption {
  id: string;
  code: string;
  account_id: string;
  redeemed_at: string;
}

export interface AdminUserDetail {
  account: AdminAccount;
  usage_history: UsageMonth[];
  redemptions: Redemption[];
  stripe: StripeSummary | null;
  notes: string | null;
  audit: AuditRow[];
}

function readStripe(raw: unknown): StripeSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const st = obj(raw);
  const sub = st.subscription && typeof st.subscription === "object" ? obj(st.subscription) : null;
  return {
    customer: str(st.customer),
    subscription: sub
      ? { id: str(sub.id), status: str(sub.status), cancel_at_period_end: sub.cancel_at_period_end === true, current_period_end: numOrNull(sub.current_period_end), trial_end: numOrNull(sub.trial_end) }
      : null,
    invoices: arr(st.invoices).map((i) => {
      const x = obj(i);
      return { id: str(x.id), number: strOrNull(x.number), status: str(x.status), total: num(x.total), currency: str(x.currency), created: num(x.created), hosted_invoice_url: strOrNull(x.hosted_invoice_url) };
    }),
    ...(typeof st.error === "string" ? { error: st.error } : {}),
  };
}

export function readUserDetail(raw: unknown): AdminUserDetail {
  const o = obj(raw);
  return {
    account: readAccount(o.account),
    usage_history: arr(o.usage_history).map((r) => ({ ...readUsage(r), account_id: str(obj(r).account_id), month: str(obj(r).month), topup_expires_at: strOrNull(obj(r).topup_expires_at) })),
    redemptions: arr(o.redemptions).map((r) => ({ id: id(obj(r).id), code: str(obj(r).code), account_id: str(obj(r).account_id), redeemed_at: str(obj(r).redeemed_at) })),
    stripe: readStripe(o.stripe),
    notes: strOrNull(o.notes),
    audit: arr(o.audit).map(readAudit),
  };
}

/** POST /admin/users/{id}/actions: `message` for a free-months code, `url` for send_portal_link. */
export interface AdminActionResult {
  ok: boolean;
  account: AdminAccount;
  message?: string;
  url?: string;
}

export function readActionResult(raw: unknown): AdminActionResult {
  const o = obj(raw);
  return {
    ok: o.ok === true,
    account: readAccount(o.account),
    ...(typeof o.message === "string" ? { message: o.message } : {}),
    ...(typeof o.url === "string" ? { url: o.url } : {}),
  };
}

// ---- promo codes ---------------------------------------------------------------------------------------------------

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
  created_by: string | null;
  created_at: string | null;
  stripe_coupon_id: string | null;
  /** percent/fixed: how many monthly invoices it repeats on (null: the first only). */
  duration_months: number | null;
}

export function readCode(raw: unknown): PromoCode {
  const o = obj(raw);
  const plans = Array.isArray(o.plan_codes) ? (o.plan_codes as PlanCode[]) : null;
  return {
    code: str(o.code),
    kind: (str(o.kind) || "percent") as CodeKind,
    value: num(o.value),
    plan_codes: plans && plans.length ? plans : null,
    max_redemptions: numOrNull(o.max_redemptions),
    redeemed_count: num(o.redeemed_count),
    expires_at: strOrNull(o.expires_at),
    active: o.active !== false,
    created_by: strOrNull(o.created_by),
    created_at: strOrNull(o.created_at),
    stripe_coupon_id: strOrNull(o.stripe_coupon_id),
    duration_months: numOrNull(o.duration_months),
  };
}

export const readCodes = (raw: unknown): PromoCode[] => arr(raw).map(readCode);

/** POST /admin/codes */
export interface CodeCreate {
  code: string;
  kind: CodeKind;
  value: number;
  plan_codes: PlanCode[] | null;
  max_redemptions: number | null;
  expires_at: string | null;
  duration_months?: number | null;
  active: boolean;
}

/** PATCH /admin/codes/{code}: the kind and value of a code are fixed once made. */
export interface CodePatch {
  active?: boolean;
  max_redemptions?: number | null;
  expires_at?: string | null;
  plan_codes?: PlanCode[] | null;
}

/** What a code gives, in words. */
export function describeCode(c: Pick<PromoCode, "kind" | "value">): string {
  if (c.kind === "percent") return `${c.value}% off`;
  if (c.kind === "fixed") return `£${(c.value / 100).toFixed(2)} off`;
  return `${c.value} month${c.value === 1 ? "" : "s"} free`;
}

// ---- plans ---------------------------------------------------------------------------------------------------------

export interface AdminPlan extends RtPlan {
  active: boolean;
  sort: number;
  stripe_price_month: string | null;
  stripe_price_year: string | null;
}

/** A plan's limits with any key the runtime left out filled from the contract's defaults by the caller. */
const readLimits = (v: unknown): PlanLimits => obj(v) as unknown as PlanLimits;

export function readPlan(raw: unknown): AdminPlan {
  const o = obj(raw);
  return {
    code: str(o.code) as PlanCode,
    name: str(o.name),
    price_month_pence: num(o.price_month_pence),
    price_year_pence: num(o.price_year_pence),
    limits: readLimits(o.limits),
    active: o.active !== false,
    sort: num(o.sort),
    stripe_price_month: strOrNull(o.stripe_price_month),
    stripe_price_year: strOrNull(o.stripe_price_year),
  };
}

export const readPlans = (raw: unknown): AdminPlan[] => arr(raw).map(readPlan);

/** PATCH /admin/plans/{code} */
export interface PlanPatch {
  name?: string;
  limits?: Partial<PlanLimits>;
  active?: boolean;
  price_month_pence?: number;
  price_year_pence?: number;
}

// ---- GET /admin/analytics ------------------------------------------------------------------------------------------

/** The product events counted under `features` (services/runtime/app/billing/registry.py FEATURE_EVENTS). */
export interface FeatureCounts {
  document_scanned: number;
  proposal_approved: number;
  bank_synced: number;
  ask: number;
  vat_export: number;
  itsa_export: number;
  ebay_sync: number;
}

export interface AdminAnalytics {
  from: string;
  to: string;
  daily_active: DayCount[];
  funnel: { signed_up: number; first_document: number; first_approval: number };
  features: FeatureCounts;
  /** Trials that ended in the range and how many of them pay; rate is null when none ended. */
  trial_conversion: { trials_ended: number; converted: number; rate: number | null };
  churn: { cancelled: number; active_at_start: number; rate: number | null };
  errors_by_route: { route: string; count: number }[];
}

export function readAnalytics(raw: unknown): AdminAnalytics {
  const o = obj(raw);
  const f = obj(o.funnel);
  const feat = obj(o.features);
  const c = obj(o.trial_conversion);
  const ch = obj(o.churn);
  return {
    from: str(o.from),
    to: str(o.to),
    daily_active: readDays(o.daily_active),
    funnel: { signed_up: num(f.signed_up), first_document: num(f.first_document), first_approval: num(f.first_approval) },
    features: {
      document_scanned: num(feat.document_scanned),
      proposal_approved: num(feat.proposal_approved),
      bank_synced: num(feat.bank_synced),
      ask: num(feat.ask),
      vat_export: num(feat.vat_export),
      itsa_export: num(feat.itsa_export),
      ebay_sync: num(feat.ebay_sync),
    },
    trial_conversion: { trials_ended: num(c.trials_ended), converted: num(c.converted), rate: numOrNull(c.rate) },
    churn: { cancelled: num(ch.cancelled), active_at_start: num(ch.active_at_start), rate: numOrNull(ch.rate) },
    errors_by_route: arr(o.errors_by_route).map((r) => ({ route: str(obj(r).route), count: num(obj(r).count) })),
  };
}

// ---- bug reports ---------------------------------------------------------------------------------------------------

export type BugStatus = "new" | "triaged" | "fixed" | "wont_fix";
export const BUG_STATUSES: BugStatus[] = ["new", "triaged", "fixed", "wont_fix"];
export const BUG_LABEL: Record<BugStatus, string> = { new: "New", triaged: "Triaged", fixed: "Fixed", wont_fix: "Won't fix" };

export interface BugReport {
  id: string;
  at: string;
  account_id: string | null;
  email: string | null;
  message: string;
  page: string | null;
  app: string;
  version: string | null;
  ua: string | null;
  /** Where the screenshot is kept; GET /admin/bug-reports/{id}/screenshot gives a short-lived link to it. */
  screenshot_path: string | null;
  status: BugStatus;
  admin_notes: string | null;
  closed_at: string | null;
}

export function readBug(raw: unknown): BugReport {
  const o = obj(raw);
  return {
    id: id(o.id),
    at: str(o.at),
    account_id: strOrNull(o.account_id),
    email: strOrNull(o.email),
    message: str(o.message),
    page: strOrNull(o.page),
    app: str(o.app),
    version: strOrNull(o.version),
    ua: strOrNull(o.ua),
    screenshot_path: strOrNull(o.screenshot_path),
    status: (str(o.status) || "new") as BugStatus,
    admin_notes: strOrNull(o.admin_notes),
    closed_at: strOrNull(o.closed_at),
  };
}

/** GET /admin/bug-reports?status=&page= */
export const readBugs = (raw: unknown): Paged<BugReport> => readPaged(raw, readBug);

/** GET /admin/bug-reports/{id}/screenshot: a signed link, good for `expires_in` seconds. */
export interface ScreenshotLink {
  url: string;
  expires_in: number;
}

export const readScreenshot = (raw: unknown): ScreenshotLink => ({ url: str(obj(raw).url), expires_in: num(obj(raw).expires_in) });

// ---- writes --------------------------------------------------------------------------------------------------------

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
