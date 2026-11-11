"use client";

/**
 * Test-mode stand-in for the billing, admin, analytics and bug-report endpoints (lib/billing-api.ts): the pages render
 * in e2e without a backend. It answers in the runtime's shapes (docs/billing/api_shapes.json). Only a
 * NEXT_PUBLIC_TEST_MODE=1 build imports it. State lives in localStorage under `accnomos.test.billing` (a spec may seed it
 * with addInitScript): {account?: partial RtAccount, admin?: boolean, configured?: false (billing off)}. Payments are
 * off as on a default runtime; `{account: {payments_provider: "stripe"}}` turns them on.
 * Every call is recorded under `accnomos.test.billing.calls` so a spec can check what the page sent.
 */
import { DEFAULT_PLANS, TRIAL_DAYS, type RtAccount, type RtAccountAnswer } from "./billing";

const KEY = "accnomos.test.billing";
const CALLS = "accnomos.test.billing.calls";

function readJson<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(window.localStorage.getItem(key) ?? "") as T;
  } catch {
    return fallback;
  }
}

function record(path: string, method: string, body: unknown) {
  const calls = readJson<unknown[]>(CALLS, []);
  calls.push({ path, method, body });
  window.localStorage.setItem(CALLS, JSON.stringify(calls));
}

class HttpError extends Error {
  constructor(public status: number, text: string) {
    super(`${text} (status ${status})`);
  }
}

const iso = (offsetDays: number) => new Date(Date.now() + offsetDays * 86_400_000).toISOString();

function account(): RtAccount {
  const saved = readJson<{ account?: Partial<RtAccount> }>(KEY, {}).account ?? {};
  const optOut = window.localStorage.getItem("accnomos.test.billing.optout") === "1";
  const limits = DEFAULT_PLANS.find((p) => p.code === (saved.plan_code ?? "comprehensive"))!.limits;
  const status = saved.status ?? "trialing";
  return {
    configured: true,
    id: "00000000-0000-4000-8000-000000000001",
    email: "sam@sambuilds.example",
    display_name: "Sam",
    plan_code: "comprehensive",
    status,
    read_only: status === "trial_ended" || status === "cancelled",
    trial_ends_at: iso(TRIAL_DAYS - 3),
    comp_until: null,
    billing_interval: null,
    current_period_end: null,
    cancel_at_period_end: false,
    has_payment_account: false,
    analytics_opt_out: optOut,
    usage: { docs: 12, ask: 30, invoices: 4, bank_feeds: 1, users: 1, marketplaces: 0, autopilot_rules: 2, topup_docs_remaining: 0, topup_expires_at: null },
    limits,
    own_ai: false,
    upgrade_url: `${window.location.origin}/settings/billing`,
    payments_provider: "none",
    ...saved,
  };
}

function accountAnswer(): RtAccountAnswer {
  if (readJson<{ configured?: boolean }>(KEY, {}).configured === false) {
    return { configured: false, detail: "Billing is not configured on this server: every feature is available without limits." };
  }
  return account();
}

const paged = <T,>(items: T[], params: URLSearchParams) => {
  const page = Number(params.get("page") ?? "1") || 1;
  return { items: items.slice((page - 1) * 25, page * 25), page, per_page: 25, total: items.length };
};

// ---- admin fixtures (in memory: a reload starts again) -----------------------------------------------------------

type U = Record<string, unknown> & { id: string; usage: Record<string, number> };
const row = (over: Record<string, unknown>): U => ({
  display_name: null, auth_subject: `email:${String(over.email)}`, trial_ends_at: null, comp_until: null, billing_interval: null, country: "GB",
  stripe_customer_id: null, stripe_subscription_id: null, current_period_end: null, cancel_at_period_end: false, notes: null, analytics_opt_out: false, ...over,
}) as unknown as U;
const users: U[] = [
  row({ id: "u-1", email: "amy@bramblejoinery.example", display_name: "Amy Bramble", auth_kind: "work", plan_code: "comprehensive", status: "trialing", created_at: iso(-20), last_seen_at: iso(-1), trial_ends_at: iso(70), usage: { docs: 41, ask: 12, invoices: 3, topup_docs_remaining: 0 }  }),
  row({ id: "u-2", email: "raj@northgatetimber.example", display_name: "Raj Patel", auth_kind: "personal", plan_code: "ultimate", status: "active", created_at: iso(-80), last_seen_at: iso(0), billing_interval: "year", stripe_customer_id: "cus_test2", stripe_subscription_id: "sub_test2", current_period_end: iso(285), usage: { docs: 700, ask: 210, invoices: 55, topup_docs_remaining: 100 }, notes: "Pays annually."  }),
  row({ id: "u-3", email: "lee@harthillbakery.example", display_name: "Lee Harthill", auth_kind: "google", plan_code: "starter", status: "past_due", created_at: iso(-50), last_seen_at: iso(-9), billing_interval: "month", stripe_customer_id: "cus_test3", stripe_subscription_id: "sub_test3", current_period_end: iso(12), usage: { docs: 50, ask: 90, invoices: 20, topup_docs_remaining: 0 }  }),
];
let auditId = 1;
const audit: Record<string, unknown>[] = [
  { id: auditId++, at: iso(-2), admin_email: "admin@accnomos.example", account_id: "u-2", action: "grant_topup", detail: { docs: 100 } },
];
const codes: Record<string, unknown>[] = [
  { code: "YEARFREE", kind: "free_months", value: 12, plan_codes: null, max_redemptions: 50, redeemed_count: 3, expires_at: null, active: true, created_by: "admin@accnomos.example", created_at: iso(-30), stripe_coupon_id: null, duration_months: null },
  { code: "WELCOME20", kind: "percent", value: 20, plan_codes: ["starter"], max_redemptions: null, redeemed_count: 8, expires_at: iso(60), active: true, created_by: "admin@accnomos.example", created_at: iso(-30), stripe_coupon_id: "co_x", duration_months: 3 },
];
const plans: Record<string, unknown>[] = DEFAULT_PLANS.map((p, i) => ({ ...p, active: true, sort: i + 1, stripe_price_month: null, stripe_price_year: null }));
const bugs: Record<string, unknown>[] = [
  { id: "b-1", at: iso(-1), account_id: "u-1", email: "amy@bramblejoinery.example", message: "The VAT page shows last quarter first.", page: "/vat", app: "web", version: "0.1.0", ua: "Chrome 140 on Linux", screenshot_path: null, status: "new", admin_notes: null, closed_at: null },
  { id: "b-2", at: iso(-6), account_id: "u-3", email: "lee@harthillbakery.example", message: "Receipt would not upload from my phone.", page: "/files", app: "android", version: "1.2.0", ua: "Android 15", screenshot_path: "u-3/b2.png", status: "triaged", admin_notes: "Looking at it.", closed_at: null },
];
/** A 1×1 PNG, standing in for the signed storage link. */
const PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8AAAgMBgO3a2wAAAABJRU5ErkJggg==";

function isAdmin() {
  return window.localStorage.getItem("accnomos.test.admin") === "1" || readJson<{ admin?: boolean }>(KEY, {}).admin === true;
}

function day(n: number) {
  return new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
}

function patch(target: Record<string, unknown>, body: unknown) {
  Object.assign(target, body as Record<string, unknown>);
}

const accountRow = (u: U) => {
  const { usage: _usage, ...rest } = u;
  void _usage;
  return rest;
};

function logAudit(accountId: string | null, action: string, detail: unknown) {
  audit.unshift({ id: auditId++, at: new Date().toISOString(), admin_email: "admin@accnomos.example", account_id: accountId, action, detail });
}

/** Answers `method path` as the runtime would; throws an Error ending "(status N)" like lib/runtime.ts. */
export async function fakeCall<T>(fullPath: string, method: string, body?: unknown): Promise<T> {
  const [path, query = ""] = fullPath.split("?");
  const params = new URLSearchParams(query);
  record(path, method, body);
  const out = (v: unknown) => v as T;

  if (path === "/plans") return out(DEFAULT_PLANS);
  if (path === "/events") {
    const n = (body as { events?: unknown[] }).events?.length ?? 1;
    return out({ accepted: n, dropped: 0 });
  }
  if (path === "/bug-reports") return out({ id: `b-${bugs.length + 1}` });
  if (path === "/account") {
    if (method === "PATCH") {
      const optOut = (body as { analytics_opt_out?: boolean }).analytics_opt_out === true;
      window.localStorage.setItem("accnomos.test.billing.optout", optOut ? "1" : "0");
    }
    return out(method === "PATCH" ? account() : accountAnswer());
  }
  if (path === "/billing/checkout" || path === "/billing/topup" || path === "/billing/portal" || path === "/billing/change-plan") {
    if (account().payments_provider === "none") throw new HttpError(503, "Paid plans can't be bought on this server.");
    return out({ url: `${window.location.origin}/settings?${account().payments_provider}=test#plan-billing` });
  }
  if (path === "/billing/cancel") {
    if (account().payments_provider === "none") throw new HttpError(503, "Paid plans can't be bought on this server.");
    const a = account();
    return out({ ok: true, message: "Cancelled: nothing more is taken", account: { ...a, cancel_at_period_end: true } });
  }
  if (path === "/billing/redeem") {
    const code = String((body as { code?: string }).code ?? "").trim().toUpperCase();
    return out(
      code === "YEARFREE"
        ? { ok: true, message: "12 months free applied.", code, kind: "free_months", account: { ...account(), status: "comped", comp_until: iso(365) } }
        : { ok: false, message: "That code is not valid.", account: account() },
    );
  }

  if (!path.startsWith("/admin/")) throw new HttpError(404, "Not found");
  if (!isAdmin()) throw new HttpError(403, "Not an administrator");

  if (path === "/admin/metrics") {
    const counts = { starter: 6, comprehensive: 11, ultimate: 3 };
    return out({
      signups_by_day: Array.from({ length: 30 }, (_, i) => ({ day: day(29 - i), count: (i * 7) % 5 })),
      total_accounts: 37, trialing: 14, active_by_plan: counts, active: 20, past_due: 1, cancelled: 2, trial_ended: 0, comped: 0,
      mrr_pence: 6 * 1000 + 11 * 2000 + 3 * 5000, trials_ending_7d: 2,
      trials_ending: [{ id: "u-1", email: "amy@bramblejoinery.example", trial_ends_at: iso(3) }, { id: "u-9", email: "kim@kimcakes.example", trial_ends_at: iso(5) }],
    });
  }
  if (path === "/admin/users") {
    const needle = (params.get("q") ?? "").toLowerCase();
    const items = users.filter(
      (u) => (!needle || String(u.email).toLowerCase().includes(needle) || String(u.display_name).toLowerCase().includes(needle)) && (!params.get("plan") || u.plan_code === params.get("plan")) && (!params.get("status") || u.status === params.get("status")),
    );
    return out(paged(items, params));
  }
  let m = /^\/admin\/users\/([^/]+)(\/actions)?$/.exec(path);
  if (m) {
    const u = users.find((x) => x.id === decodeURIComponent(m![1]));
    if (!u) throw new HttpError(404, "No such account");
    if (m[2]) {
      const a = (body as { action: string; days?: number; code?: string; docs?: number }).action;
      logAudit(u.id, a, body);
      if (a === "extend_trial") u.trial_ends_at = iso(Number(body && (body as { days: number }).days) + 30);
      if (a === "grant_topup") u.usage.topup_docs_remaining += 100;
      return out({ ok: true, account: accountRow(u), ...(a === "send_portal_link" ? { url: "https://billing.stripe.test/p/bps_test" } : {}) });
    }
    if (method === "PATCH") {
      patch(u, body);
      logAudit(u.id, "update_account", { after: body });
      return out(accountRow(u));
    }
    const paying = Boolean(u.stripe_customer_id);
    return out({
      account: accountRow(u), notes: u.notes,
      usage_history: [
        { account_id: u.id, month: day(0).slice(0, 7) + "-01", ...u.usage, topup_expires_at: null },
        { account_id: u.id, month: day(31).slice(0, 7) + "-01", docs: 20, ask: 40, invoices: 2, topup_docs_remaining: 0, topup_expires_at: null },
      ],
      redemptions: u.id === "u-2" ? [{ id: 1, code: "WELCOME20", account_id: u.id, redeemed_at: iso(-70) }] : [],
      stripe: paying
        ? {
            customer: u.stripe_customer_id,
            subscription: { id: u.stripe_subscription_id, status: u.status === "past_due" ? "past_due" : "active", cancel_at_period_end: false, current_period_end: Math.floor(Date.now() / 1000) + 12 * 86_400, trial_end: null },
            invoices: [{ id: "in_1", number: "ACC-0001", status: "paid", total: u.plan_code === "ultimate" ? 60000 : 1200, currency: "gbp", created: Math.floor(Date.now() / 1000) - 18 * 86_400, hosted_invoice_url: null }],
          }
        : null,
      audit: audit.filter((r) => r.account_id === u.id),
    });
  }
  if (path === "/admin/codes") {
    if (method === "POST") {
      const c = { redeemed_count: 0, active: true, plan_codes: null, max_redemptions: null, expires_at: null, duration_months: null, created_by: "admin@accnomos.example", created_at: new Date().toISOString(), stripe_coupon_id: null, ...(body as object) };
      codes.unshift(c);
      return out(c);
    }
    return out(codes);
  }
  m = /^\/admin\/codes\/([^/]+)$/.exec(path);
  if (m) {
    const c = codes.find((x) => x.code === decodeURIComponent(m![1]));
    if (!c) throw new HttpError(404, "No such code");
    const extra = Object.keys(body as object).filter((k) => !["active", "max_redemptions", "expires_at", "plan_codes"].includes(k));
    if (extra.length) throw new HttpError(422, `Extra inputs are not permitted: ${extra.join(", ")}`);
    patch(c, body);
    return out(c);
  }
  if (path === "/admin/plans") return out(plans);
  m = /^\/admin\/plans\/([^/]+)$/.exec(path);
  if (m) {
    const p = plans.find((x) => x.code === m![1]);
    if (!p) throw new HttpError(404, "No such plan");
    const b = body as { limits?: object };
    patch(p, { ...b, ...(b.limits ? { limits: { ...(p.limits as object), ...b.limits } } : {}) });
    return out(p);
  }
  if (path === "/admin/analytics") {
    const to = params.get("to") ?? day(0);
    const from = params.get("from") ?? day(29);
    return out({
      from, to,
      daily_active: Array.from({ length: 30 }, (_, i) => ({ day: day(29 - i), count: 5 + ((i * 3) % 9) })),
      funnel: { signed_up: 120, first_document: 84, first_approval: 61 },
      features: { document_scanned: 940, proposal_approved: 612, bank_synced: 210, ask: 388, vat_export: 31, itsa_export: 16, ebay_sync: 33 },
      trial_conversion: { trials_ended: 90, converted: 22, rate: 0.2444 }, churn: { cancelled: 2, active_at_start: 66, rate: 0.0303 },
      errors_by_route: [{ route: "POST /books/scan", count: 4 }, { route: "GET /books/bankfeeds", count: 2 }],
    });
  }
  if (path === "/admin/bug-reports") {
    const s = params.get("status");
    return out(paged(s ? bugs.filter((b) => b.status === s) : bugs, params));
  }
  m = /^\/admin\/bug-reports\/([^/]+)(\/screenshot)?$/.exec(path);
  if (m) {
    const b = bugs.find((x) => x.id === m![1]);
    if (!b) throw new HttpError(404, "No such report");
    if (m[2]) {
      if (!b.screenshot_path) throw new HttpError(404, "No screenshot for that report");
      return out({ url: PIXEL, expires_in: 600 });
    }
    if (method !== "PATCH") throw new HttpError(405, "Method Not Allowed");
    patch(b, body);
    return out(b);
  }
  if (path === "/admin/audit") {
    const id = params.get("account_id");
    return out(paged(id ? audit.filter((r) => r.account_id === id) : audit, params));
  }
  throw new HttpError(404, "Not found");
}
