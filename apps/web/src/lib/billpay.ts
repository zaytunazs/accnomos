"use client";

/**
 * Bills paid through PayPal on their due date (services/runtime/app/billpay.py, routes in routes_billpay.py).
 * Kept apart from lib/runtime.ts on purpose: same headers, its own small fetch.
 */

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { CALENDAR_SCOPES } from "./msal";
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
  version: string;
  /** "Approve now, pay on due date" (null when none, or cancelled). */
  approval: BpApproval | null;
}

export interface BpApproval {
  event_id: string;
  supplier: string;
  amount_pence: number;
  payee_email: string;
  due_date: string;
  approved_by: string;
  approved_at: string;
  status: "scheduled" | "paying" | "needs_you" | "cancelled";
  reason: string | null;
  payout_id: string | null;
}

export type BpUpcomingStatus = "scheduled" | "planned" | "due_today" | "paying" | "paid" | "needs_you";

export interface BpUpcomingItem {
  event_id: string;
  contact_id: string;
  supplier: string;
  reference: string | null;
  date: string;
  amount_pence: number;
  payee_email: string | null;
  status: BpUpcomingStatus;
  approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  reason: string | null;
  payout_id: string | null;
  calendar_uid: string;
  in_calendar: boolean;
  calendar_outdated: boolean;
  title: string;
  description: string;
}

export interface BpUpcoming {
  today: string;
  clearing_pence: number;
  clearing_label: string;
  next_7_pence: number;
  next_30_pence: number;
  shortfall_7_pence: number;
  shortfall_30_pence: number;
  warning: string | null;
  items: BpUpcomingItem[];
  calendar_stale: string[];
  note: string;
}

export interface BpCalendarResult {
  added: number;
  updated: number;
  unchanged: number;
  removed: number;
  not_found: number;
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
  scheduled_paid: BpPayout[];
  scheduled_held: { bill: string; supplier: string; amount_pence: number; reasons: string[] }[];
  problems: string[];
}

async function send(a: AccountInfo, path: string, init: RequestInit, scopes: string[]): Promise<Response> {
  const headers: Record<string, string> = { ...(await runtimeHeaders(a, scopes)) };
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
  return res;
}

async function call<T>(a: AccountInfo, path: string, init: RequestInit = {}, scopes: string[] = []): Promise<T> {
  const res = await send(a, path, init, scopes);
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
  /** Every approved-in-advance and planned PayPal payment, the 7/30-day totals and the shortfall (books figure). */
  upcoming: (a: AccountInfo) => call<BpUpcoming>(a, "/billpay/upcoming"),
  /** "Approve now, pay on due date": paid the next time Accnomos is open on or after it, if nothing changed. */
  schedule: (a: AccountInfo, b: { event_id: string; owed_pence: number; payee_email: string }, acknowledgeChangedDetails: boolean) =>
    call<BpApproval>(
      a,
      `/billpay/bills/${enc(b.event_id)}/schedule`,
      post({ amount_pence: b.owed_pence, payee_email: b.payee_email, confirm: true, acknowledge_changed_details: acknowledgeChangedDetails }),
    ),
  cancelSchedule: (a: AccountInfo, eventId: string) =>
    call<BpApproval>(a, `/billpay/bills/${enc(eventId)}/schedule/cancel`, post({ confirm: true })),
  /** The .ics text: one payment, or (no id) every one still to be sent. */
  ics: async (a: AccountInfo, eventId?: string) =>
    (await send(a, `/billpay/calendar.ics${eventId ? `?event_id=${enc(eventId)}` : ""}`, {}, [])).text(),
  /** Into the calendar the user signed in with (Google or Outlook), on their tap. Asks for calendar write access. */
  addToCalendar: (a: AccountInfo, eventIds?: string[]) =>
    call<BpCalendarResult>(a, "/billpay/calendar", post({ confirm: true, ...(eventIds ? { event_ids: eventIds } : {}) }), CALENDAR_SCOPES),
  /** Remove those events (default: the ones for payments cancelled, paid or no longer planned). */
  removeFromCalendar: (a: AccountInfo, eventIds?: string[]) =>
    call<BpCalendarResult>(a, "/billpay/calendar/remove", post({ confirm: true, ...(eventIds ? { event_ids: eventIds } : {}) }), CALENDAR_SCOPES),
};

/** Save text as a file in the browser (the .ics download). */
export function downloadText(text: string, filename: string, type = "text/calendar;charset=utf-8"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export { calendarName, paysLine, UPCOMING_STATUS } from "./billpay-text";

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
