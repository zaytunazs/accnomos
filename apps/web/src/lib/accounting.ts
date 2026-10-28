"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeHeaders } from "./runtime";

/**
 * Accounting tools: /accounting/* and the budget, cash flow and tracking reports
 * (services/runtime/app/routes_accounting.py, routes_reports.py). Money is integer pence on the wire; every figure is
 * worked out by the runtime. Only approving a journal, voiding one and a confirmed recode post to the ledger.
 */

async function detail(res: Response, what: string): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return `${body.detail} (status ${res.status})`;
    if (Array.isArray(body.detail)) {
      const first = body.detail[0] as { loc?: unknown[]; msg?: string } | undefined;
      if (first?.msg) return `${first.loc?.slice(1).join(" › ") ?? ""}: ${first.msg} (status ${res.status})`;
    }
  } catch {
    /* not JSON */
  }
  return `Could not ${what} (${res.status}): ${text.slice(0, 200)}`;
}

async function call<T>(account: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const json = typeof init.body === "string";
  const headers = { ...(await runtimeHeaders(account)), ...(json ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers: { ...headers, ...(init.headers ?? {}) } });
  if (!res.ok) throw new Error(await detail(res, `${init.method ?? "GET"} ${path}`));
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | null | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};

const body = (method: string, data: unknown): RequestInit => ({ method, body: JSON.stringify(data) });

/* ---------------------------------------------------------------------------------------------------------------- */

export type AccountType =
  | "fixed_asset" | "current_asset" | "bank" | "current_liability" | "equity" | "revenue" | "direct_costs" | "overhead";
export type VatLetter = "S" | "R" | "Z" | "E" | "O" | "N";
export const VAT_LABELS: Record<VatLetter, string> = {
  S: "Standard 20%",
  R: "Reduced 5%",
  Z: "Zero rated",
  E: "Exempt",
  O: "Outside the scope",
  N: "No VAT invoice",
};

export interface RtAccount {
  code: string;
  name: string;
  label: string;
  type: AccountType;
  vat_default: VatLetter | null;
  archived: boolean;
  system: boolean;
  description: string | null;
  postings: number;
  balance_pence: number;
}
export interface RtChart {
  accounts: RtAccount[];
  saved: boolean;
  unlisted: string[];
  types: Record<AccountType, string>;
  ranges: Record<AccountType, [number, number]>;
}
export interface RtImport {
  result: { added: string[]; updated: string[]; unchanged: number; errors: string[] };
  chart: RtChart;
}

export interface RtJournalLine {
  account: string;
  debit_pence: number;
  credit_pence: number;
  vat_code: VatLetter | null;
  description: string | null;
  tracking: Record<string, string> | null;
}
export interface RtJournal {
  id: string;
  number: string;
  status: "draft" | "posted" | "voided" | "discarded";
  source: "manual" | "depreciation" | "disposal";
  date: string;
  narration: string;
  lines: RtJournalLine[];
  vat_box: "sales" | "purchases" | null;
  net_pence: number | null;
  vat_pence: number | null;
  auto_reverse_on: string | null;
  document_path: string | null;
  warnings: string[];
  created_by: string;
  approved_by: string | null;
  event_id: string | null;
  reversal_event_id: string | null;
}
export interface JournalIn {
  date: string;
  narration: string;
  lines: { account: string; debit_pence: number; credit_pence: number; vat_code: VatLetter | null; description: string | null; tracking: Record<string, string> | null }[];
  vat_box: "sales" | "purchases" | null;
  auto_reverse_on: string | null;
  document_path: string | null;
}

export interface RtAssetState {
  accumulated_pence: number;
  depreciated_to: string | null;
  disposed_on: string | null;
  disposal_journal: string | null;
  proceeds_pence: number | null;
  gain_pence: number | null;
  pending_journal: string | null;
}
export interface RtAsset {
  id: string;
  number: string;
  name: string;
  asset_type: "plant" | "office" | "motor" | "computer" | "other";
  purchase_date: string;
  cost_pence: number;
  residual_pence: number;
  method: "none" | "straight_line" | "reducing_balance";
  rate_percent: string | null;
  life_years: number | null;
  frequency: "monthly" | "yearly";
  cost_account: string;
  accumulated_account: string;
  expense_account: string;
  state: RtAssetState;
  book_value_pence: number;
  status: "registered" | "disposed";
}
export interface RtRecon {
  account: string;
  kind: "cost" | "accumulated_depreciation";
  register_pence: number;
  ledger_pence: number;
  difference_pence: number;
}
export interface RtAssets {
  assets: RtAsset[];
  reconciliation: RtRecon[];
  note: string;
}
export interface RtSchedulePeriod {
  index: number;
  start: string;
  end: string;
  charge_pence: number;
  accumulated_pence: number;
  book_value_pence: number;
  posted: boolean;
}
export interface AssetIn {
  name: string;
  asset_type: RtAsset["asset_type"];
  purchase_date: string;
  cost_pence: number;
  residual_pence: number;
  method: RtAsset["method"];
  rate_percent: number | null;
  life_years: number | null;
  frequency: "monthly" | "yearly";
  cost_account: string | null;
  accumulated_account: string | null;
}

export interface RtFoundLine {
  event_id: string;
  line: number;
  date: string;
  kind: string;
  counterparty: string | null;
  memo: string | null;
  account: string;
  vat_code: string | null;
  debit_pence: number;
  credit_pence: number;
  recoded: boolean;
  recodable: boolean;
  vat_recodable: boolean;
  reason: string | null;
}
export interface RtRecodeResult {
  posted: boolean;
  lines_recoded: number;
  events: {
    original_event_id: string;
    date: string;
    counterparty: string | null;
    lines: { account: string; debit_pence: number; credit_pence: number; vat_code: string | null }[];
    vat_box: string | null;
    net_change_pence: number | null;
    vat_change_pence: number | null;
  }[];
}

export interface RtTrackingOption { id: string; name: string; archived: boolean }
export interface RtTrackingCategory { id: string; name: string; options: RtTrackingOption[] }
export interface RtTracking { categories: RtTrackingCategory[]; max_categories: number; used: [string, string][] }
export interface RtTrackingSummary {
  start: string;
  end: string;
  category: { id: string; name: string };
  columns: { id: string; name: string; archived: boolean }[];
  rows: { account: string; section: string; by_option: Record<string, number>; total_pence: number }[];
  totals: Record<string, Record<string, number>>;
  net_profit_total_pence: number;
  basis: string;
}

export interface RtBudget { start: string; name: string; lines: { account: string; months: number[] }[]; updated_at: string | null }
export interface RtBudgetSummary {
  start: string;
  name: string;
  months: string[];
  rows: { account: string; section: string; months: number[]; total_pence: number }[];
  section_totals: Record<string, number[]>;
  net_profit: number[];
  net_profit_total_pence: number;
}
export interface RtVarianceRow {
  account: string;
  section: string;
  budget_pence: number;
  actual_pence: number;
  variance_pence: number;
  variance_percent: number | null;
  favourable: boolean | null;
}
export interface RtVariance {
  start: string;
  name: string;
  period_start: string;
  period_end: string;
  months: number;
  rows: RtVarianceRow[];
  totals: Record<"sales" | "cost_of_sales" | "overheads" | "net_profit", RtVarianceRow>;
  basis: string;
}

export interface RtCashFlow {
  as_of: string;
  opening_balance_pence: number;
  bank_accounts: string[];
  buckets: { label: string; start: string | null; end: string; money_in_pence: number; money_out_pence: number; net_pence: number }[];
  points: { days: number; date: string; money_in_pence: number; money_out_pence: number; balance_pence: number }[];
  items: { direction: "in" | "out"; contact: string; reference: string | null; due_date: string; amount_pence: number; overdue: boolean; event_id: string }[];
  later_in_pence: number;
  later_out_pence: number;
  repeating: unknown[];
  not_included: string;
  lowest_balance_pence: number;
  lowest_on: string;
}

/* ---------------------------------------------------------------------------------------------------------------- */

export const accounting = {
  chart: (a: AccountInfo) => call<RtChart>(a, "/accounting/accounts"),
  addAccount: (a: AccountInfo, acc: { code: string; name: string; type: AccountType; vat_default: VatLetter | null }) =>
    call<RtChart>(a, "/accounting/accounts", body("POST", acc)),
  editAccount: (a: AccountInfo, code: string, edit: Record<string, unknown>) =>
    call<RtChart>(a, `/accounting/accounts/${code}`, body("PATCH", edit)),
  deleteAccount: (a: AccountInfo, code: string) => call<RtChart>(a, `/accounting/accounts/${code}`, { method: "DELETE" }),
  exportChart: async (a: AccountInfo): Promise<string> => {
    const res = await fetch(`${RUNTIME_URL}/accounting/accounts/export.csv`, { headers: await runtimeHeaders(a) });
    if (!res.ok) throw new Error(await detail(res, "export the chart"));
    return res.text();
  },
  importChart: (a: AccountInfo, csv: string) => call<RtImport>(a, "/accounting/accounts/import", body("POST", { csv })),

  journals: (a: AccountInfo, f: { status?: string; source?: string; from?: string; to?: string; account?: string; q?: string } = {}) =>
    call<{ journals: RtJournal[] }>(a, `/accounting/journals${qs(f)}`),
  createJournal: (a: AccountInfo, j: JournalIn) => call<RtJournal>(a, "/accounting/journals", body("POST", j)),
  approveJournal: (a: AccountInfo, id: string) => call<RtJournal>(a, `/accounting/journals/${id}/approve`, { method: "POST" }),
  discardJournal: (a: AccountInfo, id: string) => call<RtJournal>(a, `/accounting/journals/${id}/discard`, { method: "POST" }),
  voidJournal: (a: AccountInfo, id: string) => call<RtJournal>(a, `/accounting/journals/${id}/void`, { method: "POST" }),

  assets: (a: AccountInfo) => call<RtAssets>(a, "/accounting/assets"),
  registerAsset: (a: AccountInfo, asset: AssetIn) => call<RtAsset>(a, "/accounting/assets", body("POST", asset)),
  removeAsset: (a: AccountInfo, id: string) => call<RtAsset>(a, `/accounting/assets/${id}`, { method: "DELETE" }),
  schedule: (a: AccountInfo, id: string) =>
    call<{ asset: RtAsset; periods: RtSchedulePeriod[]; note: string }>(a, `/accounting/assets/${id}/schedule`),
  runDepreciation: (a: AccountInfo, to: string) =>
    call<{ journal: RtJournal | null; message: string }>(a, "/accounting/assets/depreciation", body("POST", { to })),
  dispose: (a: AccountInfo, id: string, d: { date: string; proceeds_pence: number; vat_pence: number }) =>
    call<RtJournal>(a, `/accounting/assets/${id}/dispose`, body("POST", d)),

  search: (a: AccountInfo, f: Record<string, string | number | null>) =>
    call<{ lines: RtFoundLine[]; truncated: boolean }>(a, `/accounting/recode/search${qs(f)}`),
  recode: (a: AccountInfo, r: { lines: { event_id: string; line: number }[]; account: string | null; vat_code: VatLetter | null; confirm: boolean }) =>
    call<RtRecodeResult>(a, "/accounting/recode", body("POST", r)),

  tracking: (a: AccountInfo) => call<RtTracking>(a, "/accounting/tracking"),
  addCategory: (a: AccountInfo, name: string) => call<RtTracking>(a, "/accounting/tracking/categories", body("POST", { name })),
  renameCategory: (a: AccountInfo, id: string, name: string) =>
    call<RtTracking>(a, `/accounting/tracking/categories/${id}`, body("PATCH", { name })),
  addOption: (a: AccountInfo, cat: string, name: string) =>
    call<RtTracking>(a, `/accounting/tracking/categories/${cat}/options`, body("POST", { name })),
  editOption: (a: AccountInfo, cat: string, opt: string, edit: { name?: string; archived?: boolean }) =>
    call<RtTracking>(a, `/accounting/tracking/categories/${cat}/options/${opt}`, body("PATCH", edit)),
  trackingSummary: (a: AccountInfo, category: string, from: string, to: string) =>
    call<RtTrackingSummary>(a, `/reports/tracking${qs({ category, from, to })}`),

  budgets: (a: AccountInfo) => call<{ budgets: RtBudget[] }>(a, "/reports/budgets"),
  saveBudget: (a: AccountInfo, start: string, b: { name: string; lines: { account: string; months: number[] }[] }) =>
    call<RtBudget>(a, `/reports/budgets/${start}`, body("PUT", b)),
  budgetSummary: (a: AccountInfo, start: string) => call<RtBudgetSummary>(a, `/reports/budgets/${start}/summary`),
  budgetVariance: (a: AccountInfo, start: string, through: string | null) =>
    call<RtVariance>(a, `/reports/budgets/${start}/variance${qs({ through })}`),

  cashflow: (a: AccountInfo) => call<RtCashFlow>(a, "/reports/cashflow"),
  cashflowLine: (a: AccountInfo) => call<{ line: string | null; model: string | null; reason: string | null }>(a, "/reports/cashflow/explain"),
};

/* ---------------------------------------------------------------------------------------------------------------- */

/** "£1,234.56" (or "-£1,234.56") from integer pence: exact, no floating point. */
export function money(pence: number): string {
  const sign = pence < 0 ? "-" : "";
  const abs = Math.abs(pence);
  const pounds = Math.floor(abs / 100).toLocaleString("en-GB");
  return `${sign}£${pounds}.${String(abs % 100).padStart(2, "0")}`;
}

/** "12.34", "£1,234.5" or "7" -> pence, by string (no floats); null when it isn't an amount. */
export function toPence(raw: string): number | null {
  const s = raw.trim().replace(/^£/, "").replace(/,/g, "");
  const m = /^(-)?(\d{0,12})(?:\.(\d{1,2}))?$/.exec(s);
  if (!s || !m || (!m[2] && !m[3])) return null;
  const pence = Number(m[2] || "0") * 100 + Number((m[3] ?? "").padEnd(2, "0") || "0");
  return m[1] ? -pence : pence;
}

/** Pence as an input's text: 1234 -> "12.34", 0 -> "". */
export const penceText = (p: number) => (p ? `${p < 0 ? "-" : ""}${Math.floor(Math.abs(p) / 100)}.${String(Math.abs(p) % 100).padStart(2, "0")}` : "");

export const ukDay = (iso: string) => {
  const d = new Date(`${iso}T12:00:00`);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
