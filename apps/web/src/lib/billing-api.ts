"use client";

/**
 * The runtime's billing, admin, analytics and bug-report endpoints (docs/billing/PLANS_AND_CONTRACT.md). A
 * test-mode build (NEXT_PUBLIC_TEST_MODE=1, e2e) answers from lib/billing-fake.ts in the browser instead, so the
 * pages render without a backend; the check is written out at each use so a normal build folds the fakes away.
 */
import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeCall, runtimeHeaders } from "./runtime";
import type { BillingInterval, RtAccount, RtPlan } from "./billing";
import {
  readAnalytics, readAuditList, readBug, readBugs, readCode, readCodes, readMetrics, readPlan, readPlans, readUserDetail, readUserList,
  type AdminAction, type AdminUserPatch, type BugStatus, type PromoCode,
} from "./admin";
import type { TrackEvent } from "./analytics-core";

type Init = { method?: string; body?: unknown };

async function rt<T>(a: AccountInfo, path: string, init: Init = {}): Promise<T> {
  const req: RequestInit = { method: init.method ?? "GET", ...(init.body !== undefined ? { body: JSON.stringify(init.body) } : {}) };
  if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
    const fake = await import("./billing-fake");
    return fake.fakeCall<T>(path, req.method ?? "GET", init.body);
  }
  return runtimeCall<T>(a, path, req);
}

const q = (params: Record<string, string | number | undefined>) => {
  const s = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");
  return s ? `?${s}` : "";
};

/** GET /plans: public, no sign-in. Null when the runtime cannot be reached (the page keeps the contract's table). */
export async function fetchPlans(): Promise<RtPlan[] | null> {
  try {
    if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
      const fake = await import("./billing-fake");
      return fake.fakeCall<RtPlan[]>("/plans", "GET");
    }
    const res = await fetch(`${RUNTIME_URL}/plans`);
    if (!res.ok) return null;
    const list = readPlans(await res.json());
    return list.length ? list.filter((p) => p.active !== false) : null;
  } catch {
    return null;
  }
}

export const billingApi = {
  account: (a: AccountInfo) => rt<RtAccount>(a, "/account"),
  /** The opt-out is not in the contract's endpoint list: PATCH /account {analytics_opt_out} (a contract addition). */
  setAnalyticsOptOut: (a: AccountInfo, optOut: boolean) => rt<RtAccount>(a, "/account", { method: "PATCH", body: { analytics_opt_out: optOut } }),
  checkout: (a: AccountInfo, body: { plan_code: string; interval: BillingInterval; promo_code?: string }) =>
    rt<{ url: string }>(a, "/billing/checkout", { method: "POST", body }),
  portal: (a: AccountInfo) => rt<{ url: string }>(a, "/billing/portal", { method: "POST" }),
  redeem: (a: AccountInfo, code: string) => rt<{ ok: boolean; message: string; account?: RtAccount }>(a, "/billing/redeem", { method: "POST", body: { code } }),
  topup: (a: AccountInfo) => rt<{ url: string }>(a, "/billing/topup", { method: "POST" }),
};

export const supportApi = {
  bugReport: (a: AccountInfo, body: { message: string; page: string; app: string; version: string; ua: string; screenshot_b64?: string }) =>
    rt<{ id: string }>(a, "/bug-reports", { method: "POST", body }),
  /** POST /events. `events` sends the batch in one request (a contract addition); the server may take only single events. */
  async sendEvents(a: AccountInfo, events: TrackEvent[]): Promise<boolean> {
    if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
      await (await import("./billing-fake")).fakeCall("/events", "POST", { events });
      return true;
    }
    const headers = { ...(await runtimeHeaders(a)), "Content-Type": "application/json" };
    const post = (body: unknown) => fetch(`${RUNTIME_URL}/events`, { method: "POST", headers, body: JSON.stringify(body), keepalive: true });
    if (!singleOnly && events.length > 1) {
      const res = await post({ events });
      if (res.ok) return true;
      if (res.status !== 400 && res.status !== 422) return false;
      singleOnly = true; // an older runtime: one event per request from now on
    }
    let ok = true;
    for (const e of events) ok = (await post(e)).ok && ok;
    return ok;
  },
};
let singleOnly = false;

export const adminApi = {
  metrics: async (a: AccountInfo) => readMetrics(await rt<unknown>(a, "/admin/metrics")),
  users: async (a: AccountInfo, p: { q?: string; plan?: string; status?: string; page?: number }) =>
    readUserList(await rt<unknown>(a, `/admin/users${q(p)}`), p.page ?? 1),
  user: async (a: AccountInfo, id: string) => readUserDetail(await rt<unknown>(a, `/admin/users/${encodeURIComponent(id)}`)),
  patchUser: (a: AccountInfo, id: string, body: AdminUserPatch) => rt<unknown>(a, `/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  action: (a: AccountInfo, id: string, body: AdminAction) => rt<{ ok?: boolean; message?: string; url?: string }>(a, `/admin/users/${encodeURIComponent(id)}/actions`, { method: "POST", body }),
  codes: async (a: AccountInfo) => readCodes(await rt<unknown>(a, "/admin/codes")),
  createCode: async (a: AccountInfo, body: Partial<PromoCode> & { code: string; kind: PromoCode["kind"]; value: number }) =>
    readCode(await rt<unknown>(a, "/admin/codes", { method: "POST", body })),
  patchCode: async (a: AccountInfo, code: string, body: Partial<PromoCode>) =>
    readCode(await rt<unknown>(a, `/admin/codes/${encodeURIComponent(code)}`, { method: "PATCH", body })),
  plans: async (a: AccountInfo) => readPlans(await rt<unknown>(a, "/admin/plans")),
  patchPlan: async (a: AccountInfo, code: string, body: { limits?: Record<string, unknown>; active?: boolean; price_month_pence?: number; price_year_pence?: number }) =>
    readPlan(await rt<unknown>(a, `/admin/plans/${encodeURIComponent(code)}`, { method: "PATCH", body })),
  analytics: async (a: AccountInfo, p: { from?: string; to?: string } = {}) => readAnalytics(await rt<unknown>(a, `/admin/analytics${q(p)}`)),
  bugs: async (a: AccountInfo, p: { status?: string; page?: number } = {}) => readBugs(await rt<unknown>(a, `/admin/bug-reports${q(p)}`)),
  bug: async (a: AccountInfo, id: string) => readBug(await rt<unknown>(a, `/admin/bug-reports/${encodeURIComponent(id)}`)),
  patchBug: async (a: AccountInfo, id: string, body: { status?: BugStatus; admin_notes?: string }) =>
    readBug(await rt<unknown>(a, `/admin/bug-reports/${encodeURIComponent(id)}`, { method: "PATCH", body })),
  audit: async (a: AccountInfo, p: { account_id?: string; page?: number } = {}) => readAuditList(await rt<unknown>(a, `/admin/audit${q(p)}`)),
};
