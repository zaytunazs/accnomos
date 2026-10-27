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
  return {
    "X-Graph-Token": token,
    "X-Account-Kind": isPersonalAccount(account) ? "personal" : "work",
    "X-User": account.username,
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
  scan: (a: AccountInfo) => call<{ proposals: RtProposal[]; errors: { path: string; error: string }[] }>(a, "/books/scan", { method: "POST" }),
  proposals: (a: AccountInfo, status?: string) => call<RtProposal[]>(a, `/books/proposals${status ? `?status=${status}` : ""}`),
  approve: (a: AccountInfo, id: string, body: { edits?: Record<string, unknown>; always?: boolean }) =>
    call<RtProposal>(a, `/books/proposals/${id}/approve`, { method: "POST", body: JSON.stringify(body) }),
  reject: (a: AccountInfo, id: string, reason: string) =>
    call<RtProposal>(a, `/books/proposals/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  summary: (a: AccountInfo) => call<RtSummary>(a, "/books/summary"),
};

export const gbp = (n: number) => `£${n.toFixed(2)}`;
export const ukDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
