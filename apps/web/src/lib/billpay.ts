"use client";

/**
 * Bills paid through PayPal on their due date (services/runtime/app/billpay.py, routes in routes_billpay.py).
 * Kept apart from lib/runtime.ts on purpose: same headers, its own small fetch.
 */

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeHeaders } from "./runtime";

export type BpPlan = "paypal" | "not_paypal" | null;
export type BpStatus = "sending" | "pending" | "unclaimed" | "paid" | "failed" | "unknown";

export interface BpPayout {
  id: string;
  event_id: string;
  contact_id: string;
  supplier: string;
  reference: string | null;
  amount_pence: number;
  receiver: string;
  attempt: number;
  via: "owner" | "autopilot";
  approved_by: string;
  status: BpStatus;
  paypal_status: string | null;
  detail: string | null;
  batch_id: string | null;
  item_id: string | null;
  fee_pence: number | null;
  payment_id: string | null;
  problem: string | null;
  created_at: string;
  updated_at: string;
}

export interface BpBill {
  event_id: string;
  contact_id: string;
  supplier: string;
  reference: string | null;
  bill_date: string;
  due_date: string;
  days_overdue: number;
  gross_pence: number;
  owed_pence: number;
  person_approved: boolean;
  plan: BpPlan;
  payee_email: string | null;
  due_now: boolean;
  can_pay: boolean;
  blocks: string[];
  warnings: string[];
  changed_details: string[];
  details_checked: "checked" | "nothing to check" | "unreadable" | "not yet";
  autopilot: string[];
  payout: BpPayout | null;
}

export interface BpPayee {
  contact_id: string;
  name: string;
  paypal_email: string;
  bank: string | null;
  confirmed_at: string;
  confirmed_by: string;
}

export interface BpRule {
  contact_id: string;
  enabled: boolean;
  max_per_bill_pence: number;
  monthly_cap_pence: number;
  min_days_unchanged: number;
  only_person_approved: boolean;
}

export interface BpAutopilot {
  enabled: boolean;
  rules: BpRule[];
  changed_at: string | null;
  stopped_at: string | null;
}

export interface BpFlag {
  id: string;
  contact_id: string;
  supplier: string;
  event_id: string;
  reason: string;
  at: string;
}

export interface BpNotice {
  id: string;
  at: string;
  text: string;
  kind: "paid" | "asked" | "flag" | "problem";
}

export interface BpOverview {
  today: string;
  available: boolean;
  reason: string | null;
  connected: boolean;
  test_mode: boolean;
  clearing_pence: number;
  due: BpBill[];
  upcoming: BpBill[];
  payees: BpPayee[];
  payouts: BpPayout[];
  flags: BpFlag[];
  notices: BpNotice[];
  autopilot: BpAutopilot;
  autopilot_note: string;
}

export interface BpRunResult {
  refreshed: BpPayout[];
  paid: BpPayout[];
  asked: { bill: string; supplier: string; owed_pence: number; reasons: string[] }[];
  problems: string[];
}

async function call<T>(a: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(await runtimeHeaders(a)) };
  if (typeof init.body === "string") headers["Content-Type"] = "application/json";
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail = "";
    try {
      const d = (JSON.parse(text) as { detail?: unknown }).detail;
      detail = typeof d === "string" ? d : "";
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `Could not ${init.method ?? "GET"} ${path} (${res.status})`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const billpay = {
  overview: (a: AccountInfo) => call<BpOverview>(a, "/billpay"),
  /** On opening the page: follow payouts on their way, then Autopilot pays what its rules allow. */
  run: (a: AccountInfo) => call<BpRunResult>(a, "/billpay/run", { method: "POST" }),
  setPayee: (a: AccountInfo, contactId: string, paypalEmail: string, bank: string | null) =>
    call<BpPayee>(a, `/billpay/payees/${enc(contactId)}`, put({ paypal_email: paypalEmail, bank, confirm: true })),
  removePayee: (a: AccountInfo, contactId: string) => call<void>(a, `/billpay/payees/${enc(contactId)}`, { method: "DELETE" }),
  setPlan: (a: AccountInfo, eventId: string, plan: BpPlan) =>
    call<{ plan: BpPlan }>(a, `/billpay/bills/${enc(eventId)}/plan`, put({ plan })),
  pay: (a: AccountInfo, eventId: string, amountPence: number, acknowledgeChangedDetails: boolean) =>
    call<BpPayout>(
      a,
      `/billpay/bills/${enc(eventId)}/pay`,
      post({ amount_pence: amountPence, confirm: true, acknowledge_changed_details: acknowledgeChangedDetails }),
    ),
  clearFlag: (a: AccountInfo, flagId: string) => call<BpFlag>(a, `/billpay/flags/${enc(flagId)}/clear`, post({ confirm: true })),
  saveAutopilot: (a: AccountInfo, enabled: boolean, rules: BpRule[]) =>
    call<BpAutopilot>(a, "/billpay/autopilot", put({ enabled, rules })),
  stopAutopilot: (a: AccountInfo) => call<BpAutopilot>(a, "/billpay/autopilot/stop", { method: "POST" }),
  noticesSeen: (a: AccountInfo, ids: string[]) => call<void>(a, "/billpay/notices/seen", post({ ids })),
};

/** "12.50" or "£1,200" -> pence, exactly (no floats); null when it is not an amount. */
export function penceFromPounds(input: string): number | null {
  const s = input.replace(/[£,\s]/g, "");
  const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(s);
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "0").padEnd(2, "0"));
}

export function poundsFromPence(pence: number): string {
  return `${Math.floor(pence / 100)}.${String(pence % 100).padStart(2, "0")}`;
}
