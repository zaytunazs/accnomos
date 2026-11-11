"use client";

/**
 * The runtime's billing, admin, analytics and bug-report endpoints (docs/billing/PLANS_AND_CONTRACT.md). A
 * test-mode build (NEXT_PUBLIC_TEST_MODE=1, e2e) answers from lib/billing-fake.ts in the browser instead, so the
 * pages render without a backend; the check is written out at each use so a normal build folds the fakes away.
 */
import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeCall, runtimeHeaders } from "./runtime";
import type { BillingInterval, RedeemResult, RtAccount, RtAccountAnswer, RtPlan } from "./billing";
import {
  readAccount, readActionResult, readAnalytics, readAuditList, readBug, readBugs, readCode, readCodes, readMetrics, readPlan, readPlans,
  readScreenshot, readUserDetail, readUserList,
  type AdminAction, type AdminUserPatch, type BugStatus, type CodeCreate, type CodePatch, type PlanPatch,
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
    return list.length ? list : null;
  } catch {
    return null;
  }
}

export const billingApi = {
  /** GET /account: `{configured: false}` when the runtime has no billing (then the plan UI stays out of the way). */
  account: (a: AccountInfo) => rt<RtAccountAnswer>(a, "/account"),
  /** PATCH /account {analytics_opt_out}: Settings › Privacy. */
  setAnalyticsOptOut: (a: AccountInfo, optOut: boolean) => rt<RtAccount>(a, "/account", { method: "PATCH", body: { analytics_opt_out: optOut } }),
  checkout: (a: AccountInfo, body: { plan_code: string; interval: BillingInterval; promo_code?: string }) =>
    rt<{ url: string }>(a, "/billing/checkout", { method: "POST", body }),
  portal: (a: AccountInfo) => rt<{ url: string }>(a, "/billing/portal", { method: "POST" }),
  redeem: (a: AccountInfo, code: string) => rt<RedeemResult>(a, "/billing/redeem", { method: "POST", body: { code } }),
  topup: (a: AccountInfo) => rt<{ url: string }>(a, "/billing/topup", { method: "POST" }),
};

export const supportApi = {
  bugReport: (a: AccountInfo, body: { message: string; page: string; app: string; version: string; ua: string; screenshot_b64?: string }) =>
    rt<{ id: string }>(a, "/bug-reports", { method: "POST", body }),
  /**
   * POST /events {events: [...]}: one request for the batch (up to 20; the runtime checks each event on its own and
   * drops one its rules refuse without losing the rest). Answers {accepted, dropped}.
   */
  async sendEvents(a: AccountInfo, events: TrackEvent[]): Promise<boolean> {
    if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
      await (await import("./billing-fake")).fakeCall("/events", "POST", { events });
      return true;
    }
    if (events.length === 0) return true;
    const headers = { ...(await runtimeHeaders(a)), "Content-Type": "application/json" };
    let ok = true;
    for (let i = 0; i < events.length; i += MAX_EVENTS) {
      const body = JSON.stringify({ events: events.slice(i, i + MAX_EVENTS) });
      ok = (await fetch(`${RUNTIME_URL}/events`, { method: "POST", headers, body, keepalive: true })).ok && ok;
    }
    return ok;
  },
};
/** The runtime's batch size (services/runtime/app/billing/analytics.py MAX_BATCH). */
export const MAX_EVENTS = 20;

export const adminApi = {
  metrics: async (a: AccountInfo) => readMetrics(await rt<unknown>(a, "/admin/metrics")),
  users: async (a: AccountInfo, p: { q?: string; plan?: string; status?: string; page?: number }) => readUserList(await rt<unknown>(a, `/admin/users${q(p)}`)),
  user: async (a: AccountInfo, id: string) => readUserDetail(await rt<unknown>(a, `/admin/users/${encodeURIComponent(id)}`)),
  patchUser: async (a: AccountInfo, id: string, body: AdminUserPatch) => readAccount(await rt<unknown>(a, `/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body })),
  action: async (a: AccountInfo, id: string, body: AdminAction) =>
    readActionResult(await rt<unknown>(a, `/admin/users/${encodeURIComponent(id)}/actions`, { method: "POST", body })),
  codes: async (a: AccountInfo) => readCodes(await rt<unknown>(a, "/admin/codes")),
  createCode: async (a: AccountInfo, body: CodeCreate) => readCode(await rt<unknown>(a, "/admin/codes", { method: "POST", body })),
  patchCode: async (a: AccountInfo, code: string, body: CodePatch) =>
    readCode(await rt<unknown>(a, `/admin/codes/${encodeURIComponent(code)}`, { method: "PATCH", body })),
  plans: async (a: AccountInfo) => readPlans(await rt<unknown>(a, "/admin/plans")),
  patchPlan: async (a: AccountInfo, code: string, body: PlanPatch) =>
    readPlan(await rt<unknown>(a, `/admin/plans/${encodeURIComponent(code)}`, { method: "PATCH", body })),
  analytics: async (a: AccountInfo, p: { from?: string; to?: string } = {}) => readAnalytics(await rt<unknown>(a, `/admin/analytics${q(p)}`)),
  bugs: async (a: AccountInfo, p: { status?: string; page?: number } = {}) => readBugs(await rt<unknown>(a, `/admin/bug-reports${q(p)}`)),
  patchBug: async (a: AccountInfo, id: string, body: { status?: BugStatus; admin_notes?: string }) =>
    readBug(await rt<unknown>(a, `/admin/bug-reports/${encodeURIComponent(id)}`, { method: "PATCH", body })),
  /** A signed link to the report's screenshot, valid for a few minutes. */
  screenshot: async (a: AccountInfo, id: string) => readScreenshot(await rt<unknown>(a, `/admin/bug-reports/${encodeURIComponent(id)}/screenshot`)),
  audit: async (a: AccountInfo, p: { account_id?: string; page?: number } = {}) => readAuditList(await rt<unknown>(a, `/admin/audit${q(p)}`)),
};
