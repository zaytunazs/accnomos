/**
 * The keys of every billing, account, analytics and admin response the apps read, written out against their types,
 * so `tests/unit/api-shapes.test.ts` can compare them with the runtime's pinned shapes (docs/billing/api_shapes.json,
 * written by services/runtime/tests/test_billing_contract.py). `Spec<T>` makes tsc insist that every key of the type is
 * listed and no other; the unit test insists that the list is exactly the runtime's. A key added, renamed or dropped on
 * either side fails CI. `{}` marks a free-form object (an audit entry's `detail`). Pure: type-only imports.
 */
import type { AdminAccount, AdminActionResult, AdminAnalytics, AdminMetrics, AdminPlan, AdminUserDetail, AdminUserRow, AuditRow, BugReport, Paged, PromoCode, ScreenshotLink } from "./admin";
import type { EventsResult } from "./analytics-core";
import type { CancelResult, PlanLimits, RedeemResult, RtAccount, RtAccountOff, RtPlan, StripeRedirect } from "./billing";
import type { PlanLimitBody, ReadOnlyBody } from "./plan-limit";

type Leaf<V> = [V] extends [readonly (infer E)[]] ? (E extends object ? [Spec<E>] : true) : [V] extends [object] ? Spec<V> : true;
/** Every key of T: `true` for a value, a nested Spec for an object, `[Spec]` for a list of objects. */
export type Spec<T> = { [K in keyof T]-?: Leaf<NonNullable<T[K]>> };

const LIMITS: Spec<PlanLimits> = {
  users: true, docs: true, ask: true, bank_feeds: true, invoices: true, marketplaces: true, payroll_employees: true, autopilot_rules: true,
  multi_currency: true, projects: true, support: true,
};
const PLAN: Spec<RtPlan> = { code: true, name: true, price_month_pence: true, price_year_pence: true, limits: LIMITS };
const ACCOUNT: Spec<RtAccount> = {
  configured: true, id: true, email: true, display_name: true, plan_code: true, status: true, read_only: true, trial_ends_at: true,
  comp_until: true, billing_interval: true, current_period_end: true, cancel_at_period_end: true, has_payment_account: true,
  analytics_opt_out: true, own_ai: true, upgrade_url: true, payments_provider: true, limits: LIMITS,
  usage: { docs: true, ask: true, invoices: true, bank_feeds: true, users: true, marketplaces: true, autopilot_rules: true, topup_docs_remaining: true, topup_expires_at: true },
};
const ACCOUNT_OFF: Spec<RtAccountOff> = { configured: true, detail: true };
const REDEEM: Spec<RedeemResult> = { ok: true, message: true, code: true, kind: true, account: ACCOUNT };
const CANCEL: Spec<CancelResult> = { ok: true, message: true, account: ACCOUNT };
const REDIRECT: Spec<StripeRedirect> = { url: true };
const EVENTS: Spec<EventsResult> = { accepted: true, dropped: true };
const PLAN_LIMIT: Spec<PlanLimitBody> = { code: true, counter: true, limit: true, used: true, upgrade_url: true, detail: true };
const READ_ONLY: Spec<ReadOnlyBody> = { code: true, status: true, upgrade_url: true, detail: true };

const ADMIN_ACCOUNT: Spec<AdminAccount> = {
  id: true, email: true, display_name: true, auth_kind: true, auth_subject: true, created_at: true, last_seen_at: true, plan_code: true,
  status: true, trial_ends_at: true, comp_until: true, stripe_customer_id: true, stripe_subscription_id: true, billing_interval: true,
  current_period_end: true, cancel_at_period_end: true, country: true, notes: true, analytics_opt_out: true,
};
const USER_ROW: Spec<AdminUserRow> = { ...ADMIN_ACCOUNT, usage: { docs: true, ask: true, invoices: true, topup_docs_remaining: true } };
const AUDIT: Spec<AuditRow> = { id: true, at: true, admin_email: true, account_id: true, action: true, detail: {} };
const PAGE = { page: true, per_page: true, total: true } as const;
const USERS: Spec<Paged<AdminUserRow>> = { items: [USER_ROW], ...PAGE };
const AUDITS: Spec<Paged<AuditRow>> = { items: [AUDIT], ...PAGE };
const METRICS: Spec<AdminMetrics> = {
  signups_by_day: [{ day: true, count: true }], total_accounts: true, trialing: true, active_by_plan: { starter: true, comprehensive: true, ultimate: true },
  active: true, past_due: true, cancelled: true, trial_ended: true, comped: true, mrr_pence: true, trials_ending_7d: true,
  trials_ending: [{ id: true, email: true, trial_ends_at: true }],
};
const USER_DETAIL: Spec<AdminUserDetail> = {
  account: ADMIN_ACCOUNT,
  usage_history: [{ account_id: true, month: true, docs: true, ask: true, invoices: true, topup_docs_remaining: true, topup_expires_at: true }],
  redemptions: [{ id: true, code: true, account_id: true, redeemed_at: true }],
  stripe: {
    customer: true,
    subscription: { id: true, status: true, cancel_at_period_end: true, current_period_end: true, trial_end: true },
    invoices: [{ id: true, number: true, status: true, total: true, currency: true, created: true, hosted_invoice_url: true }],
    error: true,
  },
  notes: true,
  audit: [AUDIT],
};
const ACTION: Spec<AdminActionResult> = { ok: true, account: ADMIN_ACCOUNT, message: true, url: true };
const CODE: Spec<PromoCode> = {
  code: true, kind: true, value: true, plan_codes: true, max_redemptions: true, redeemed_count: true, expires_at: true, active: true,
  created_by: true, created_at: true, stripe_coupon_id: true, duration_months: true,
};
const ADMIN_PLAN: Spec<AdminPlan> = { ...PLAN, active: true, sort: true, stripe_price_month: true, stripe_price_year: true };
const ANALYTICS: Spec<AdminAnalytics> = {
  from: true, to: true, daily_active: [{ day: true, count: true }],
  funnel: { signed_up: true, first_document: true, first_approval: true },
  features: { document_scanned: true, proposal_approved: true, bank_synced: true, ask: true, vat_export: true, itsa_export: true, ebay_sync: true },
  trial_conversion: { trials_ended: true, converted: true, rate: true },
  churn: { cancelled: true, active_at_start: true, rate: true },
  errors_by_route: [{ route: true, count: true }],
};
const BUG: Spec<BugReport> = {
  id: true, at: true, account_id: true, email: true, message: true, page: true, app: true, version: true, ua: true, screenshot_path: true,
  status: true, admin_notes: true, closed_at: true,
};
const BUGS: Spec<Paged<BugReport>> = { items: [BUG], ...PAGE };
const SCREENSHOT: Spec<ScreenshotLink> = { url: true, expires_in: true };

/** One entry per name in docs/billing/api_shapes.json. A list answer is `[spec]`. */
export const WIRE: Record<string, unknown> = {
  "GET /plans": [PLAN],
  "GET /account": ACCOUNT,
  "GET /account (billing off)": ACCOUNT_OFF,
  "PATCH /account": ACCOUNT,
  "POST /billing/redeem": REDEEM,
  "POST /billing/checkout": REDIRECT,
  "POST /billing/portal": REDIRECT,
  "POST /billing/change-plan": REDIRECT,
  "POST /billing/cancel": CANCEL,
  "POST /billing/topup": REDIRECT,
  "POST /events (batch)": EVENTS,
  "POST /bug-reports": { id: true },
  "402 plan_limit": PLAN_LIMIT,
  "402 read_only": READ_ONLY,
  "GET /admin/metrics": METRICS,
  "GET /admin/users": USERS,
  "GET /admin/users/{id}": USER_DETAIL,
  "PATCH /admin/users/{id}": ADMIN_ACCOUNT,
  "POST /admin/users/{id}/actions": ACTION,
  "GET /admin/codes": [CODE],
  "POST /admin/codes": CODE,
  "PATCH /admin/codes/{code}": CODE,
  "GET /admin/plans": [ADMIN_PLAN],
  "PATCH /admin/plans/{code}": ADMIN_PLAN,
  "GET /admin/audit": AUDITS,
  "GET /admin/analytics": ANALYTICS,
  "GET /admin/bug-reports": BUGS,
  "PATCH /admin/bug-reports/{id}": BUG,
  "GET /admin/bug-reports/{id}/screenshot": SCREENSHOT,
};

/** Keys the runtime sends only sometimes (so a snapshot may lack them). */
export const OPTIONAL = new Set(["POST /admin/users/{id}/actions.message", "POST /admin/users/{id}/actions.url", "GET /admin/users/{id}.stripe.error"]);
/** Free-form objects: their keys are not part of the contract. */
export const OPAQUE = new Set(["GET /admin/audit.items[].detail", "GET /admin/users/{id}.audit[].detail"]);
