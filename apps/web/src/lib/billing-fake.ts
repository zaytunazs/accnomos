"use client";

/**
 * Test-mode stand-in for the billing, admin, analytics and bug-report endpoints (lib/billing-api.ts): the pages render
 * in e2e without a backend. Only a NEXT_PUBLIC_TEST_MODE=1 build imports it. State lives in localStorage under
 * `accnomos.test.billing` (a spec may seed it with addInitScript): {account?: partial RtAccount, admin?: boolean}.
 * Every call is recorded under `accnomos.test.billing.calls` so a spec can check what the page sent.
 */
import { DEFAULT_PLANS, TRIAL_DAYS, type RtAccount } from "./billing";

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
  return {
    id: "00000000-0000-4000-8000-000000000001",
    email: "sam@sambuilds.example",
    plan_code: "comprehensive",
    status: "trialing",
    trial_ends_at: iso(TRIAL_DAYS - 3),
    comp_until: null,
    billing_interval: null,
    usage: { docs: 12, ask: 30, invoices: 4, bank_feeds: 1, users: 1, marketplaces: 0, topup_docs_remaining: 0 },
    limits,
    own_ai: false,
    analytics_opt_out: optOut,
    ...saved,
  };
}

// ---- admin fixtures (in memory: a reload starts again) -----------------------------------------------------------

type U = Record<string, unknown> & { id: string };
const users: U[] = [
  { id: "u-1", email: "amy@bramblejoinery.example", display_name: "Amy Bramble", auth_kind: "work", plan_code: "comprehensive", status: "trialing", created_at: iso(-20), last_seen_at: iso(-1), trial_ends_at: iso(70), comp_until: null, billing_interval: null, country: "GB", usage: { docs: 41, ask: 12, invoices: 3, topup_docs_remaining: 0 }, notes: "" },
  { id: "u-2", email: "raj@northgatetimber.example", display_name: "Raj Patel", auth_kind: "personal", plan_code: "ultimate", status: "active", created_at: iso(-80), last_seen_at: iso(0), trial_ends_at: null, comp_until: null, billing_interval: "year", country: "GB", usage: { docs: 700, ask: 210, invoices: 55, topup_docs_remaining: 100 }, notes: "Pays annually." },
  { id: "u-3", email: "lee@harthillbakery.example", display_name: "Lee Harthill", auth_kind: "google", plan_code: "starter", status: "past_due", created_at: iso(-50), last_seen_at: iso(-9), trial_ends_at: null, comp_until: null, billing_interval: "month", country: "GB", usage: { docs: 50, ask: 90, invoices: 20, topup_docs_remaining: 0 }, notes: "" },
];
const audit: Record<string, unknown>[] = [
  { id: "a-1", at: iso(-2), admin_email: "admin@accnomos.example", account_id: "u-2", action: "grant_topup", detail: { docs: 100 } },
];
const codes: Record<string, unknown>[] = [
  { code: "YEARFREE", kind: "free_months", value: 12, plan_codes: null, max_redemptions: 50, redeemed_count: 3, expires_at: null, active: true, created_by: "admin@accnomos.example", stripe_coupon_id: null },
  { code: "WELCOME20", kind: "percent", value: 20, plan_codes: ["starter"], max_redemptions: null, redeemed_count: 8, expires_at: iso(60), active: true, created_by: "admin@accnomos.example", stripe_coupon_id: "co_x" },
];
const plans: Record<string, unknown>[] = DEFAULT_PLANS.map((p, i) => ({ ...p, active: true, sort: i }));
const bugs: Record<string, unknown>[] = [
  { id: "b-1", at: iso(-1), account_id: "u-1", email: "amy@bramblejoinery.example", message: "The VAT page shows last quarter first.", page: "/vat", app: "web", version: "0.1.0", ua: "Chrome 140 on Linux", screenshot_path: null, status: "new", admin_notes: "" },
  { id: "b-2", at: iso(-6), account_id: "u-3", email: "lee@harthillbakery.example", message: "Receipt would not upload from my phone.", page: "/files", app: "android", version: "1.2.0", ua: "Android 15", screenshot_path: "bugs/b-2.png", status: "triaged", admin_notes: "Looking at it." },
];

function isAdmin() {
  return window.localStorage.getItem("accnomos.test.admin") === "1" || readJson<{ admin?: boolean }>(KEY, {}).admin === true;
}

function day(n: number) {
  return new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
}

function patch(target: Record<string, unknown>, body: unknown) {
  Object.assign(target, body as Record<string, unknown>);
}

/** Answers `method path` as the runtime would; throws an Error ending "(status N)" like lib/runtime.ts. */
export async function fakeCall<T>(fullPath: string, method: string, body?: unknown): Promise<T> {
  const [path, query = ""] = fullPath.split("?");
  const params = new URLSearchParams(query);
  record(path, method, body);
  const out = (v: unknown) => v as T;

  if (path === "/plans") return out(DEFAULT_PLANS);
  if (path === "/events") return out({});
  if (path === "/bug-reports") return out({ id: `b-${bugs.length + 1}` });
  if (path === "/account") {
    if (method === "PATCH") {
      const optOut = (body as { analytics_opt_out?: boolean }).analytics_opt_out === true;
      window.localStorage.setItem("accnomos.test.billing.optout", optOut ? "1" : "0");
    }
    return out(account());
  }
  if (path === "/billing/checkout" || path === "/billing/topup" || path === "/billing/portal") {
    return out({ url: `${window.location.origin}/settings?stripe=test#plan-billing` });
  }
  if (path === "/billing/redeem") {
    const code = String((body as { code?: string }).code ?? "").trim().toUpperCase();
    return out(code === "YEARFREE" ? { ok: true, message: "12 months free applied.", account: { ...account(), status: "comped", comp_until: iso(365) } } : { ok: false, message: "That code is not valid." });
  }

  if (!path.startsWith("/admin/")) throw new HttpError(404, "Not found");
  if (!isAdmin()) throw new HttpError(403, "Not an administrator");

  if (path === "/admin/metrics") {
    return out({
      signups: Array.from({ length: 30 }, (_, i) => ({ day: day(29 - i), count: (i * 7) % 5 })),
      trialing: 14, active_by_plan: { starter: 6, comprehensive: 11, ultimate: 3 }, past_due: 1, cancelled: 2, mrr_pence: 6 * 1000 + 11 * 2000 + 3 * 5000, trials_ending_7d: 2,
    });
  }
  if (path === "/admin/users") {
    const needle = (params.get("q") ?? "").toLowerCase();
    const items = users.filter(
      (u) => (!needle || String(u.email).toLowerCase().includes(needle) || String(u.display_name).toLowerCase().includes(needle)) && (!params.get("plan") || u.plan_code === params.get("plan")) && (!params.get("status") || u.status === params.get("status")),
    );
    return out({ items, total: items.length, page: 1, page_size: 25 });
  }
  let m = /^\/admin\/users\/([^/]+)(\/actions)?$/.exec(path);
  if (m) {
    const u = users.find((x) => x.id === decodeURIComponent(m![1]));
    if (!u) throw new HttpError(404, "No such account");
    if (m[2]) {
      const a = (body as { action: string; days?: number; code?: string; docs?: number }).action;
      audit.unshift({ id: `a-${audit.length + 1}`, at: new Date().toISOString(), admin_email: "admin@accnomos.example", account_id: u.id, action: a, detail: body });
      if (a === "extend_trial") u.trial_ends_at = iso(Number(body && (body as { days: number }).days) + 30);
      if (a === "grant_topup") (u.usage as Record<string, number>).topup_docs_remaining += 100;
      return out({ ok: true, message: a === "send_portal_link" ? "Portal link sent." : "Done.", url: a === "send_portal_link" ? "https://billing.example/portal" : undefined });
    }
    if (method === "PATCH") {
      patch(u, body);
      audit.unshift({ id: `a-${audit.length + 1}`, at: new Date().toISOString(), admin_email: "admin@accnomos.example", account_id: u.id, action: "update", detail: body });
      return out(u);
    }
    return out({
      account: u, notes: u.notes,
      usage_history: [{ month: day(0).slice(0, 7) + "-01", ...(u.usage as object) }, { month: day(31).slice(0, 7) + "-01", docs: 20, ask: 40, invoices: 2, topup_docs_remaining: 0 }],
      redemptions: u.id === "u-2" ? [{ code: "WELCOME20", redeemed_at: iso(-70) }] : [],
      stripe: u.status === "trialing" ? { customer_id: null, subscription: null, invoices: [] } : { customer_id: "cus_test", subscription: { id: "sub_test", status: u.status === "past_due" ? "past_due" : "active", current_period_end: iso(12), cancel_at_period_end: false }, invoices: [{ id: "in_1", created: iso(-18), amount_pence: u.plan_code === "ultimate" ? 50000 : 1000, status: "paid", url: null }] },
      audit: audit.filter((r) => r.account_id === u.id),
    });
  }
  if (path === "/admin/codes") {
    if (method === "POST") {
      const c = { redeemed_count: 0, active: true, plan_codes: null, max_redemptions: null, expires_at: null, ...(body as object) };
      codes.unshift(c);
      return out(c);
    }
    return out(codes);
  }
  m = /^\/admin\/codes\/([^/]+)$/.exec(path);
  if (m) {
    const c = codes.find((x) => x.code === decodeURIComponent(m![1]));
    if (!c) throw new HttpError(404, "No such code");
    patch(c, body);
    return out(c);
  }
  if (path === "/admin/plans") return out(plans);
  m = /^\/admin\/plans\/([^/]+)$/.exec(path);
  if (m) {
    const p = plans.find((x) => x.code === m![1]);
    if (!p) throw new HttpError(404, "No such plan");
    patch(p, body);
    return out(p);
  }
  if (path === "/admin/analytics") {
    return out({
      daily_active: Array.from({ length: 30 }, (_, i) => ({ day: day(29 - i), count: 5 + ((i * 3) % 9) })),
      funnel: { signed_up: 120, first_document: 84, first_approval: 61 },
      features: { documents_scanned: 940, approvals: 612, bank_syncs: 210, ask_questions: 388, vat_itsa_exports: 47, ebay_syncs: 33 },
      conversion: { trials: 90, converted: 22, rate: 0.244 }, churn: { cancelled: 2, rate: 0.03 },
      errors: [{ route: "POST /books/scan", count: 4 }, { route: "GET /bank/feed", count: 2 }],
    });
  }
  if (path === "/admin/bug-reports") {
    const s = params.get("status");
    return out(s ? bugs.filter((b) => b.status === s) : bugs);
  }
  m = /^\/admin\/bug-reports\/([^/]+)$/.exec(path);
  if (m) {
    const b = bugs.find((x) => x.id === m![1]);
    if (!b) throw new HttpError(404, "No such report");
    if (method === "PATCH") patch(b, body);
    return out(b);
  }
  if (path === "/admin/audit") {
    const id = params.get("account_id");
    return out(id ? audit.filter((r) => r.account_id === id) : audit);
  }
  throw new HttpError(404, "Not found");
}
