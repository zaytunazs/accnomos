"use client";

import { useSyncExternalStore } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { accessToken, relay, type ClientFacts, type RelayResult } from "./hmrc";
import { runtimeHeaders, type RtBasis } from "./runtime";

/**
 * Making Tax Digital for Income Tax (self-employment), HMRC sandbox only. HMRC is reached through the relay
 * (services/hmrc-relay/relay/itsa.py) with the Income Tax session's own token; the figures come from the runtime
 * (GET /books/self-employment/summary, code), and receipts go back to the runtime, which keeps them in the books.
 */

/** Settings › Business › "I am self-employed". Off by default; it shows the Self-employment page in the menu. */
const SELF_EMPLOYED_KEY = "accnomos.selfEmployed";
const listeners = new Set<() => void>();

export function selfEmployed(): boolean {
  try {
    return window.localStorage.getItem(SELF_EMPLOYED_KEY) === "1";
  } catch {
    return false;
  }
}

export function setSelfEmployed(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(SELF_EMPLOYED_KEY, "1");
    else window.localStorage.removeItem(SELF_EMPLOYED_KEY);
  } catch {
    /* storage unavailable: the choice lives for this page only */
  }
  listeners.forEach((l) => l());
}

export function useSelfEmployed(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      window.addEventListener("storage", l);
      return () => {
        listeners.delete(l);
        window.removeEventListener("storage", l);
      };
    },
    selfEmployed,
    () => false,
  );
}

/**
 * HMRC's final declaration, word for word from the Income Tax MTD end-to-end service guide ("Agreeing to the
 * declaration", checked 28 Oct 2026). Same text in services/runtime/app/itsa.py and services/hmrc-relay/relay/itsa.py.
 */
export const FINAL_DECLARATION =
  "I declare that the information and tax return I have submitted are (taken together) correct and complete to " +
  "the best of my knowledge. I understand that I may have to pay financial penalties and face prosecution if I " +
  "give false information.";

const NINO_KEY = "accnomos.itsa.nino";
export const NINO_RE = /^[A-Z]{2}\d{6}[A-D]$/;
export const cleanNino = (s: string) => s.replace(/\s+/g, "").toUpperCase();

export function savedNino(): string {
  try {
    return window.localStorage.getItem(NINO_KEY) ?? "";
  } catch {
    return "";
  }
}
export function rememberNino(nino: string): void {
  try {
    window.localStorage.setItem(NINO_KEY, nino);
  } catch {
    /* not remembered */
  }
}

/** '2026-27' for a day from 6 April 2026 to 5 April 2027 (the runtime has the same rule: app/itsa.py). */
export function taxYearOf(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const start = m > 4 || (m === 4 && d >= 6) ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

// --- HMRC (relay) wire types, as HMRC documents them -----------------------------------------------------------

/** Business Details 2.0, List All Businesses. */
export interface ItsaBusiness {
  typeOfBusiness: "self-employment" | "uk-property" | "foreign-property" | "property-unspecified";
  businessId: string;
  tradingType?: string;
  tradingName?: string;
}
/** Obligations 3.0, income and expenditure. */
export interface ItsaObligationDetail {
  periodStartDate: string;
  periodEndDate: string;
  dueDate: string;
  status: "open" | "fulfilled";
  receivedDate?: string;
}
export interface ItsaObligations {
  obligations: { typeOfBusiness: string; businessId: string; obligationDetails: ItsaObligationDetail[] }[];
}
/** Individual Calculations 8.0, Retrieve: the parts the page reads; everything else is kept as HMRC sent it. */
export interface ItsaCalculation {
  metadata: { calculationId: string; taxYear: string; calculationType: string; calculationTimestamp?: string };
  calculation?: Record<string, unknown>;
  messages?: { info?: { id: string; text: string }[]; warnings?: { id: string; text: string }[]; errors?: { id: string; text: string }[] };
}

async function call<T>(path: string, facts: ClientFacts, extra: Record<string, unknown>, scenario?: string): Promise<RelayResult<T>> {
  const body = { client_facts: facts, method: "WEB_APP_VIA_SERVER", ...(scenario?.trim() ? { gov_test_scenario: scenario.trim() } : {}), ...extra };
  return relay<RelayResult<T>>(path, { method: "POST", body: JSON.stringify(body), token: await accessToken("itsa") });
}

export const itsa = {
  businesses: (nino: string, facts: ClientFacts, scenario?: string) =>
    call<{ listOfBusinesses: ItsaBusiness[] }>(`/itsa/${nino}/businesses`, facts, {}, scenario),
  obligations: (nino: string, facts: ClientFacts, q: { from: string; to: string; business_id?: string }, scenario?: string) =>
    call<ItsaObligations>(`/itsa/${nino}/obligations`, facts, q, scenario),
  submit: (nino: string, businessId: string, taxYear: string, facts: ClientFacts, summary: Record<string, unknown>, scenario?: string) =>
    call<null>(`/itsa/${nino}/self-employment/${businessId}/cumulative/${taxYear}`, facts, { summary, confirmed: true }, scenario),
  trigger: (nino: string, taxYear: string, facts: ClientFacts, type: "in-year" | "intent-to-finalise", scenario?: string) =>
    call<{ calculationId: string }>(`/itsa/${nino}/calculations/${taxYear}/trigger`, facts, { calculation_type: type }, scenario),
  calculation: (nino: string, taxYear: string, id: string, facts: ClientFacts, scenario?: string) =>
    call<ItsaCalculation>(`/itsa/${nino}/calculations/${taxYear}/${id}/view`, facts, {}, scenario),
  finalDeclaration: (nino: string, taxYear: string, id: string, facts: ClientFacts, scenario?: string) =>
    call<null>(`/itsa/${nino}/calculations/${taxYear}/${id}/final-declaration`, facts,
      { declaration: FINAL_DECLARATION, confirmed: true }, scenario),
};

// --- runtime -------------------------------------------------------------------------------------------------------

export interface RtSeContribution {
  event_id: string;
  date: string;
  kind: string;
  counterparty: string | null;
  account: string;
  memo: string | null;
  pence: number;
  disallowable: boolean;
  /** Cash basis only: the money behind the line. */
  source?: "payment" | "bank_line" | "applied_credit" | "refund" | "on_its_date" | null;
  paid_how?: string | null;
  money_pence?: number | null;
  document_event_id?: string | null;
  document_ref?: string | null;
  document_gross_pence?: number | null;
  payment_id?: string | null;
}
export interface RtSeLeftOut {
  date: string;
  event_id: string | null;
  description: string;
  pence: number;
  reason: string;
}
export interface RtSeFigure {
  key: string;
  group: "income" | "expenses";
  box: number;
  disallowable_box: number | null;
  label: string;
  pence: number;
  disallowable_pence: number;
  lines: RtSeContribution[];
}
export interface RtSeSummary {
  tax_year: string;
  period_start: string;
  period_end: string;
  accounting_basis: RtBasis;
  basis_label: string;
  basis: string;
  income_pence: number;
  expenses_pence: number;
  disallowable_pence: number;
  allowable_pence: number;
  net_profit_pence: number;
  figures: RtSeFigure[];
  event_ids: string[];
  unmapped_accounts: string[];
  left_out: RtSeLeftOut[];
  warnings: string[];
  can_submit: boolean;
  blockers: string[];
  hmrc_body: Record<string, unknown>;
}
export interface RtItsaReceipt {
  kind: "cumulative" | "calculation" | "final_declaration";
  path: string;
  saved_at: string;
  business_id: string | null;
  period_end: string | null;
  calculation_id: string | null;
  correlation_id: string | null;
  matches_books: boolean | null;
  accounting_basis?: RtBasis | null;
  environment: string;
}
export interface RtItsaReceiptIn {
  kind: RtItsaReceipt["kind"];
  tax_year: string;
  nino: string;
  business_id?: string;
  period_end?: string;
  calculation_id?: string;
  sent?: Record<string, unknown>;
  hmrc: RelayResult<unknown>;
  confirmed_at?: string;
  declaration?: string;
  basis?: RtBasis;
}
/** Settings › Business › Accounting basis (GET/PUT /books/self-employment/settings). */
export interface RtSeSettings {
  accounting_basis: RtBasis;
  label: string;
  default: RtBasis;
  saved: boolean;
}
export type ReportKind = "sa103" | "quarterly" | "calculation";
/** A report as rows (services/runtime/app/itsa_reports.py `Report`); the files are the same rows. */
export interface RtReport {
  kind: ReportKind;
  title: string;
  subtitle: string;
  source: string;
  notes: string[];
  sections: { title: string; columns: string[]; money: number[]; rows: (string | number | null)[][] }[];
  filename: string;
}
export type ReportFormat = "csv" | "xlsx" | "pdf";

async function rt<T>(account: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const headers = { ...(await runtimeHeaders(account)), ...(init.body ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const b = (await res.json()) as { detail?: unknown };
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b);
    } catch {
      /* not JSON */
    }
    throw new Error(`The books service said: ${detail}`);
  }
  return (await res.json()) as T;
}

export const itsaBooks = {
  settings: (a: AccountInfo) => rt<RtSeSettings>(a, "/books/self-employment/settings"),
  /** Changes how the figures are worked out; the ledger and saved receipts stay as they are. Audited. */
  saveSettings: (a: AccountInfo, basis: RtBasis) =>
    rt<RtSeSettings>(a, "/books/self-employment/settings", { method: "PUT", body: JSON.stringify({ accounting_basis: basis }) }),
  /** On the basis in Settings. */
  summary: (a: AccountInfo, taxYear: string, periodEnd: string) =>
    rt<RtSeSummary>(a, `/books/self-employment/summary?tax_year=${taxYear}&period_end=${periodEnd}`),
  receipts: (a: AccountInfo, taxYear: string) =>
    rt<{ tax_year: string; receipts: RtItsaReceipt[] }>(a, `/books/self-employment/receipts?tax_year=${taxYear}`),
  saveReceipt: (a: AccountInfo, body: RtItsaReceiptIn) =>
    rt<{ path: string; matches_books?: boolean }>(a, "/books/self-employment/receipts", { method: "POST", body: JSON.stringify(body) }),
  /** A report as rows, for the page to draw (GET /books/self-employment/reports/{kind}, JSON). */
  report: (a: AccountInfo, kind: ReportKind, query: Record<string, string>) =>
    rt<RtReport>(a, `/books/self-employment/reports/${kind}?${new URLSearchParams(query)}`),
  /** A report file (CSV, XLSX or PDF) from GET /books/self-employment/reports/{kind}, downloaded in the browser. */
  async download(a: AccountInfo, kind: ReportKind, query: Record<string, string>, format: ReportFormat): Promise<void> {
    const q = new URLSearchParams({ ...query, format });
    const res = await fetch(`${RUNTIME_URL}/books/self-employment/reports/${kind}?${q}`, { headers: await runtimeHeaders(a) });
    if (!res.ok) throw new Error(`Couldn't make the ${format.toUpperCase()} (${res.status}).`);
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `${kind}.${format}`;
    const url = URL.createObjectURL(await res.blob());
    const link = Object.assign(document.createElement("a"), { href: url, download: name });
    link.click();
    URL.revokeObjectURL(url);
  },
};

/** Pence to "£1,234.56" (negative as "−£12.00"). */
export function gbp(pence: number): string {
  const s = (Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${pence < 0 ? "−" : ""}£${s}`;
}

/** HMRC's own figure (pounds, as HMRC returned it), or a dash when HMRC left it out. Never our own number. */
export function hmrcPounds(v: unknown): string {
  return typeof v === "number" ? gbp(Math.round(v * 100)) : "—";
}
