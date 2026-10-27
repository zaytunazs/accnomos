"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { aiHeaders, loadAiConfig, RUNTIME_URL } from "./ai-config";
import { accountKind, getToken, isPersonalAccount, mailScopesFor, mailSendScopesFor, storageScopesFor } from "./msal";

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
  /** How the photo was cropped before extraction; "none" = original used. Chip: crop.note. */
  crop?: { method: "sam" | "code" | "none"; box: [number, number, number, number] | null; note: string } | null;
  verification?: RtVerification | null;
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

/** Autopilot posting is on only at level L2 (Settings › Autopilot level, localStorage `accnomos.autopilot`).
 *  L0/L1 (the default) make every scan send `X-Autopilot: off`, so nothing is posted without the user. */
const AUTOPILOT_LEVEL_KEY = "accnomos.autopilot";
export function autopilotOn(): boolean {
  try {
    return window.localStorage.getItem(AUTOPILOT_LEVEL_KEY) === "L2";
  } catch {
    return false;
  }
}
export function setAutopilotOn(on: boolean): void {
  try {
    window.localStorage.setItem(AUTOPILOT_LEVEL_KEY, on ? "L2" : "L1");
  } catch {
    /* storage unavailable — the choice lives for this page only */
  }
}
/** Independent second reading (app/ai/verify.py); `agree` is decided by code, values are never merged. */
export interface RtFieldAgreement {
  extractor: string | number | null;
  verifier: string | number | null;
  agree: boolean;
}
export interface RtVerification {
  fields: Record<string, RtFieldAgreement>;
  agree_all: boolean;
  model: string;
  elapsed_s?: number | null;
  error?: string | null;
}
export interface RtSummary {
  proposed: number;
  needs_a_look: number;
  posted_this_month: number;
  last_scan?: string | null;
}

/**
 * Headers for every runtime call: the user's Graph token + AI config. Nothing is stored server-side.
 * `extraScopes` widens the one Graph token (e.g. Mail.Read for /mail/scan, which also writes to OneDrive).
 */
export async function runtimeHeaders(account: AccountInfo, extraScopes: string[] = []): Promise<Record<string, string>> {
  const token = await getToken([...storageScopesFor(account), ...extraScopes]);
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

async function call<T>(account: AccountInfo, path: string, init: RequestInit = {}, extraScopes: string[] = []): Promise<T> {
  const headers = { ...(await runtimeHeaders(account, extraScopes)), ...(init.body ? { "Content-Type": "application/json" } : {}) };
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
  /** POST /books/ask: numbers from code, words from the user's model, every figure checked against the facts. */
  ask: (a: AccountInfo, question: string, period?: RtAskPeriod | null, history: RtAskTurn[] = []) =>
    call<RtAskAnswer>(a, "/books/ask", {
      method: "POST",
      body: JSON.stringify({ question, period: period ?? null, history: history.slice(-6) }),
    }),
  mailScan: (a: AccountInfo, body: { since_days?: number; dry_run?: boolean }) =>
    call<RtMailScan>(a, "/mail/scan", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /** POST /books/rebuild: regenerate Books.xlsx from the event files now. */
  rebuild: (a: AccountInfo) => call<RtRebuild>(a, "/books/rebuild", { method: "POST" }),
  /** GET /books/deadlines?stagger=1 | start_month=5 | months=1 (see lib/business.ts deadlinesQuery). */
  deadlines: (a: AccountInfo, query: string) => call<RtDeadlines>(a, `/books/deadlines?${query}`),

  /** /invoices/* (services/runtime/app/routes_invoices.py). Totals and VAT are worked out by the runtime. */
  invoices: (a: AccountInfo, status?: RtInvoiceStatus) => call<RtInvoice[]>(a, `/invoices${status ? `?status=${status}` : ""}`),
  invoice: (a: AccountInfo, id: string) => call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}`),
  createInvoice: (a: AccountInfo, draft: RtInvoiceDraft) =>
    call<RtInvoice>(a, "/invoices", { method: "POST", body: JSON.stringify(draft) }),
  updateInvoice: (a: AccountInfo, id: string, draft: RtInvoiceDraft) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(draft) }),
  invoicePdf: (a: AccountInfo, id: string) => call<RtInvoicePdf>(a, `/invoices/${encodeURIComponent(id)}/pdf`, { method: "POST" }),
  /** Sends from the user's Outlook. Call only from the confirmation dialog: `confirm: true` is the user's tap. */
  sendInvoice: (a: AccountInfo, id: string, email: { to: string; subject: string; body: string }) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/send`, { method: "POST", body: JSON.stringify({ ...email, confirm: true }) },
      mailSendScopesFor(accountKind(a))),
  markInvoicePaid: (a: AccountInfo, id: string, body: { payment_ref?: string; paid_on?: string; bank_line_id?: string | null }) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/mark-paid`, { method: "POST", body: JSON.stringify(body) }),
  invoiceBankCandidates: (a: AccountInfo, id: string) => call<RtBankLine[]>(a, `/invoices/${encodeURIComponent(id)}/bank-candidates`),
  voidInvoice: (a: AccountInfo, id: string, reason: string) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/void`, { method: "POST", body: JSON.stringify({ reason }) }),
  /** Drafting sends nothing; the user reads, edits and confirms before reminderSend. */
  reminderDraft: (a: AccountInfo, id: string) =>
    call<RtReminderDraft>(a, `/invoices/${encodeURIComponent(id)}/reminder-draft`, { method: "POST" }),
  reminderSend: (a: AccountInfo, id: string, email: { to: string; subject: string; body: string }) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/reminder-send`, { method: "POST", body: JSON.stringify({ ...email, confirm: true }) },
      mailSendScopesFor(accountKind(a))),
  invoiceCustomers: (a: AccountInfo) => call<RtInvoiceCustomer[]>(a, "/invoices/customers"),
  invoiceProfile: (a: AccountInfo) => call<RtInvoiceProfile>(a, "/invoices/profile"),
  saveInvoiceProfile: (a: AccountInfo, profile: RtInvoiceProfile) =>
    call<RtInvoiceProfile>(a, "/invoices/profile", { method: "PUT", body: JSON.stringify(profile) }),
  /** PNG or JPEG up to 1 MB, saved in _System/Invoicing in the user's folder. */
  uploadInvoiceLogo: async (a: AccountInfo, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${RUNTIME_URL}/invoices/profile/logo`, { method: "POST", headers: await runtimeHeaders(a), body: form });
    if (!res.ok) throw new Error(`runtime POST /invoices/profile/logo -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
    return (await res.json()) as RtInvoiceProfile;
  },
};

/** Sales invoices (services/runtime/app/invoicing.py). Money is integer pence. */
export type RtInvoiceStatus = "draft" | "sent" | "paid" | "void";
export type RtSalesVatCode = "S" | "R" | "Z" | "E" | "O";
export interface RtInvoiceCustomer {
  contact_id: string | null;
  name: string;
  email: string | null;
  address: string | null;
  vrn: string | null;
}
export interface RtInvoiceLineIn {
  description: string;
  quantity: string | number; // up to 3 decimal places; the runtime returns it as a string
  unit: string | null;
  unit_price_pence: number;
  vat_code: RtSalesVatCode;
}
export interface RtInvoiceLine extends RtInvoiceLineIn {
  vat_rate: number;
  net_pence: number;
  vat_pence: number;
}
export interface RtInvoiceDraft {
  customer: RtInvoiceCustomer;
  issue_date: string | null; // YYYY-MM-DD
  due_date: string | null;
  lines: RtInvoiceLineIn[];
  reference: string | null;
  notes: string | null;
}
export interface RtInvoice {
  number: string;
  status: RtInvoiceStatus;
  customer: RtInvoiceCustomer;
  issue_date: string;
  due_date: string;
  lines: RtInvoiceLine[];
  vat_summary: { vat_code: RtSalesVatCode; vat_rate: number; net_pence: number; vat_pence: number }[];
  net_pence: number;
  vat_pence: number;
  total_pence: number;
  reference: string | null;
  notes: string | null;
  sent_at: string | null;
  sent_to: string | null;
  event_id: string | null;
  paid_at: string | null;
  payment_ref: string | null;
  bank_line_id: string | null;
  voided_at: string | null;
  void_reason: string | null;
  reminders: { sent_at: string; to: string; subject: string }[];
  days_overdue: number | null; // only while sent and unpaid; 0 or less = not due yet
}
export interface RtInvoicePdf {
  path: string;
  size: number;
  sha256: string;
  data_url: string;
  email: { to: string | null; subject: string; body: string };
  problems: string[]; // why it cannot be sent yet
}
export interface RtReminderDraft {
  to: string | null;
  subject: string;
  body: string;
  days_overdue: number;
  model: string;
  fallback_reason: string | null; // the model's words were replaced by a draft written by code
}
export interface RtInvoiceProfile {
  name: string;
  address: string;
  email: string | null;
  phone: string | null;
  vrn: string | null;
  company_number: string | null;
  bank: { account_name: string; sort_code: string; account_number: string; iban: string | null };
  logo_path: string | null;
  terms_days: number;
  footer_note: string | null;
}
export interface RtBankLine {
  id: string;
  date: string;
  amount_pence: number;
  description: string;
  reference: string | null;
  status: "unmatched" | "matched" | "suggested";
}

/** POST /books/rebuild (services/runtime/app/routes_books.py). */
export interface RtRebuild {
  path: string;
  size: number;
  books_url: string | null;
}

/** GET /books/deadlines (services/runtime/app/routes_vat.py). Dates are YYYY-MM-DD. */
export interface RtPeriodDeadline {
  start: string;
  end: string;
  label: string;
  period_key: string | null;
  deadline: string;
  days_to_end: number;
  days_remaining: number;
  box5: string; // pounds, 2 dp, absolute
  box5_direction: "pay" | "reclaim" | "nil";
  entries: number;
}
export interface RtDeadlines {
  today: string;
  months: number;
  start_month: number;
  stagger: number | null;
  current: RtPeriodDeadline;
  due: RtPeriodDeadline | null;
  rule: string;
}

/** POST /books/ask (services/runtime/app/routes_ask.py). */
export interface RtAskPeriod {
  start: string; // YYYY-MM-DD
  end: string;
}
export interface RtAskTurn {
  role: "user" | "assistant";
  text: string;
}
export interface RtKeyNumber {
  label: string;
  value: string;
  source: string;
}
export interface RtSuggestedAction {
  label: string;
  kind: "open_review" | "open_vat" | "chase_supplier" | "none";
  arg: string | null;
}
export interface RtAskAnswer {
  answer_md: string;
  key_numbers: RtKeyNumber[];
  citations: string[];
  suggested_actions: RtSuggestedAction[];
  confidence: "high" | "medium" | "low";
  model: string;
  period: RtAskPeriod;
  fallback_reason: string | null; // the model's words were replaced by the facts, quoted by code
}


/** POST /mail/scan (services/runtime/app/intake.py): Outlook attachments copied into 00 Inbox. */
export interface RtMailScan {
  scanned: number;
  candidates: number;
  saved: string[];
  skipped_duplicates: number;
  dry_run: boolean;
  errors: { message?: string; attachment?: string; error: string }[];
  items: { name: string; subject: string; from_address: string; score: number }[];
}

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
