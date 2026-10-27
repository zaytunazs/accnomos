"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { aiHeaders, loadAiConfig, RUNTIME_URL } from "./ai-config";
import { getToken, isPersonalAccount, storageScopesFor } from "./msal";

/** Runtime wire types (services/runtime/app/schemas.py). */
export interface RtCheck {
  code: string;
  ok: boolean;
  severity: "fail" | "warn";
  message: string;
}
export interface RtLine {
  description: string;
  qty: number;
  unit_price: number;
  net: number;
  vat_rate: number | null;
  vat: number;
}
export interface RtExtracted {
  doc_type: string;
  supplier_name: string;
  supplier_vat_number: string | null;
  customer_name: string | null;
  invoice_number: string | null;
  date: string;
  currency: string;
  lines: RtLine[];
  net_total: number;
  vat_total: number;
  gross_total: number;
  payment_method: string | null;
  card_last4: string | null;
  category_guess: string;
  confidence: number;
}
export interface RtJournalLine {
  account: string;
  debit_pence: number;
  credit_pence: number;
  vat_code: string | null;
}
export interface RtProposal {
  id: string;
  doc_sha256: string;
  extracted: RtExtracted;
  checks: RtCheck[];
  status: "proposed" | "needs_a_look" | "posted" | "rejected";
  reasons: string[];
  suggested_filename: string;
  journal_draft: RtJournalLine[];
  model: string;
  elapsed_s: number;
  source_path?: string;
  decided_by?: string | null;
  decided_at?: string | null;
  event_id?: string | null;
  autopilot?: { auto_approve: boolean; reasons: string[]; supplier_key: string | null } | null;
}
/** An Autopilot rule (services/runtime/app/autopilot.py), stored in _System/Rules/rules.json. */
export interface RtRule {
  supplier_key: string;
  supplier_name: string;
  category: string;
  account: string | null;
  vat_code: string | null;
  side: "purchase" | "sale";
  typical_gross_pence: number;
  vrn: string | null;
  created_at: string;
  created_from_proposal_id: string;
  hits: number;
}

/** Autopilot master switch: lives on this device only; "off" makes scans send `X-Autopilot: off`. */
const AUTOPILOT_SWITCH_KEY = "accnomos.autopilot.switch";
export function autopilotOn(): boolean {
  try {
    return window.localStorage.getItem(AUTOPILOT_SWITCH_KEY) !== "off";
  } catch {
    return true;
  }
}
export function setAutopilotOn(on: boolean): void {
  try {
    window.localStorage.setItem(AUTOPILOT_SWITCH_KEY, on ? "on" : "off");
  } catch {
    /* storage unavailable — the switch lives for this page only */
  }
}
export interface RtSummary {
  proposed: number;
  needs_a_look: number;
  posted_this_month: number;
  last_scan?: string | null;
}

/** Headers for every runtime call: the user's Graph token + AI config. Nothing is stored server-side. */
export async function runtimeHeaders(account: AccountInfo): Promise<Record<string, string>> {
  const token = await getToken(storageScopesFor(account));
  const ai = loadAiConfig();
  let business = "";
  try {
    business = (JSON.parse(window.localStorage.getItem("accnomos.business") ?? "{}") as { name?: string }).name ?? "";
  } catch {
    /* no business details yet */
  }
  return {
    "X-Graph-Token": token,
    "X-Account-Kind": isPersonalAccount(account) ? "personal" : "work",
    "X-User": account.username,
    ...(business ? { "X-Business-Name": business } : {}),
    ...(ai ? aiHeaders(ai) : {}),
  };
}

async function call<T>(account: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const headers = { ...(await runtimeHeaders(account)), ...(init.body ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers: { ...headers, ...(init.headers ?? {}) } });
  if (!res.ok) throw new Error(`runtime ${init.method ?? "GET"} ${path} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return (await res.json()) as T;
}

export const runtime = {
  scan: (a: AccountInfo) =>
    call<{ proposals: RtProposal[]; errors: { path: string; error: string }[] }>(a, "/books/scan", {
      method: "POST",
      headers: autopilotOn() ? {} : { "X-Autopilot": "off" },
    }),
  proposals: (a: AccountInfo, status?: string) => call<RtProposal[]>(a, `/books/proposals${status ? `?status=${status}` : ""}`),
  approve: (a: AccountInfo, id: string, body: { edits?: Record<string, unknown>; remember?: boolean }) =>
    call<RtProposal>(a, `/books/approve/${id}`, { method: "POST", body: JSON.stringify(body) }),
  undo: (a: AccountInfo, eventId: string) =>
    call<{ proposal: RtProposal | null }>(a, `/books/undo/${eventId}`, { method: "POST" }),
  rules: (a: AccountInfo) => call<RtRule[]>(a, "/books/rules"),
  removeRule: (a: AccountInfo, key: string) =>
    call<RtRule>(a, `/books/rules/${encodeURIComponent(key)}`, { method: "DELETE" }),
  reject: (a: AccountInfo, id: string, reason: string) =>
    call<RtProposal>(a, `/books/proposals/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  summary: (a: AccountInfo) => call<RtSummary>(a, "/books/summary"),
};

/** GET /books/vat (services/runtime/app/routes_vat.py): the 9 boxes computed by code from posted events. */
export interface RtVatBox {
  box: number;
  label: string;
  amount: string; // pounds, 2 dp for boxes 1-5, whole for 6-9
  entries: number;
}
export interface RtVatView {
  period_key: string;
  start: string;
  end: string;
  boxes: RtVatBox[];
  event_ids: string[];
  warnings: string[];
  events_in_period: number;
  hmrc_body: Record<string, unknown>;
}

let liveVat: { account: string; promise: Promise<RtVatView> } | null = null;

/** The live return, fetched once per page per account (LiveVat and ConnectHmrc both read it). */
export function fetchLiveVat(account: AccountInfo): Promise<RtVatView> {
  if (!liveVat || liveVat.account !== account.homeAccountId) {
    const promise = call<RtVatView>(account, "/books/vat");
    promise.catch(() => {
      if (liveVat?.promise === promise) liveVat = null; // let a later mount retry
    });
    liveVat = { account: account.homeAccountId, promise };
  }
  return liveVat.promise;
}

export const gbp = (n: number) => `£${n.toFixed(2)}`;
export const ukDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
