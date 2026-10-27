"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { aiHeaders, loadAiConfig, RUNTIME_URL } from "./ai-config";
import type { PlanVat } from "./business";
import {
  accountKind,
  CALENDAR_READ_SCOPES,
  CALENDAR_SCOPES,
  contactsScopesFor,
  getToken,
  isPersonalAccount,
  mailScopesFor,
  storageScopesFor,
} from "./msal";

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
  const json = typeof init.body === "string"; // FormData sets its own multipart Content-Type
  const headers = { ...(await runtimeHeaders(account, extraScopes)), ...(json ? { "Content-Type": "application/json" } : {}) };
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
  /** `edits.job_id` tags a purchase to a job (its net then counts as a job cost). */
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
  /** POST /books/ask/voice: a spoken question, transcribed by Muse Voice (key mode only), then the same answer. */
  askVoice: (a: AccountInfo, audio: Blob, period?: RtAskPeriod | null, history: RtAskTurn[] = []) => {
    const form = new FormData();
    const ext = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
    form.append("audio", audio, `question.${ext}`);
    if (period) form.append("period", JSON.stringify(period));
    form.append("history", JSON.stringify(history.slice(-6)));
    return call<RtAskVoiceAnswer>(a, "/books/ask/voice", { method: "POST", body: form });
  },
  mailScan: (a: AccountInfo, body: { since_days?: number; dry_run?: boolean }) =>
    call<RtMailScan>(a, "/mail/scan", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /** POST /books/rebuild: regenerate Books.xlsx from the event files now. */
  rebuild: (a: AccountInfo) => call<RtRebuild>(a, "/books/rebuild", { method: "POST" }),
  /** GET /books/deadlines?stagger=1 | start_month=5 | months=1 (see lib/business.ts deadlinesQuery). */
  deadlines: (a: AccountInfo, query: string) => call<RtDeadlines>(a, `/books/deadlines?${query}`),

  /** POST /plan/day: proposes a day and writes nothing. Asks for Calendars.Read the first time. */
  planDay: (a: AccountInfo, body: RtPlanRequest) =>
    call<RtPlan>(a, "/plan/day", { method: "POST", body: JSON.stringify(body) }, CALENDAR_READ_SCOPES),
  /** POST /plan/day/apply: the plan's new items become calendar events. Asks for Calendars.ReadWrite only now. */
  applyPlan: (a: AccountInfo, date: string, plan: RtPlanItem[]) =>
    call<RtPlanApplied>(a, "/plan/day/apply", { method: "POST", body: JSON.stringify({ date, plan }) }, CALENDAR_SCOPES),

  /** Jobs, staff and timesheets (services/runtime/app/routes_jobs.py). */
  jobs: (a: AccountInfo) => call<RtJobSummary[]>(a, "/jobs"),
  /** Plain open jobs (no ledger read), for pickers. */
  openJobs: (a: AccountInfo) => call<RtJob[]>(a, "/jobs/list?status=open"),
  jobSummary: (a: AccountInfo, id: string) => call<RtJobSummary>(a, `/jobs/${encodeURIComponent(id)}/summary`),
  createJob: (a: AccountInfo, body: RtJobIn) => call<RtJob>(a, "/jobs", { method: "POST", body: JSON.stringify(body) }),
  updateJob: (a: AccountInfo, id: string, body: RtJobIn) =>
    call<RtJob>(a, `/jobs/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  /** Proposed lines from unbilled billable hours; marks nothing. */
  jobInvoiceLines: (a: AccountInfo, id: string) =>
    call<RtInvoiceProposal>(a, `/jobs/${encodeURIComponent(id)}/invoice-lines`, { method: "POST" }),
  /** Only after the invoice has been sent. */
  markInvoiced: (a: AccountInfo, id: string, invoiceId: string, entryIds: string[]) =>
    call<RtTimesheetEntry[]>(a, `/jobs/${encodeURIComponent(id)}/mark-invoiced`, {
      method: "POST",
      body: JSON.stringify({ invoice_id: invoiceId, entry_ids: entryIds }),
    }),
  staff: (a: AccountInfo) => call<RtStaff[]>(a, "/staff"),
  createStaff: (a: AccountInfo, body: RtStaffIn) => call<RtStaff>(a, "/staff", { method: "POST", body: JSON.stringify(body) }),
  updateStaff: (a: AccountInfo, id: string, body: RtStaffIn) =>
    call<RtStaff>(a, `/staff/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  timesheets: (a: AccountInfo, jobId: string) => call<RtTimesheetEntry[]>(a, `/timesheets?job_id=${encodeURIComponent(jobId)}`),
  addTimesheet: (a: AccountInfo, body: RtTimesheetIn) =>
    call<RtTimesheetEntry>(a, "/timesheets", { method: "POST", body: JSON.stringify(body) }),
  deleteTimesheet: (a: AccountInfo, id: string) =>
    call<RtTimesheetEntry>(a, `/timesheets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** /contacts/* (services/runtime/app/routes_contacts.py): money is worked out from the ledger on each call. */
  contacts: (a: AccountInfo) => call<RtContactList>(a, "/contacts"),
  refreshContacts: (a: AccountInfo) => call<RtContactList>(a, "/contacts/refresh", { method: "POST" }),
  editContact: (a: AccountInfo, id: string, edits: Partial<Record<RtContactField, string | null>>) =>
    call<RtContact>(a, `/contacts/${id}`, { method: "PUT", body: JSON.stringify(edits) }),
  importOutlookContacts: (a: AccountInfo, addNew: boolean) =>
    call<RtContactImport>(a, "/contacts/import-outlook", { method: "POST", body: JSON.stringify({ add_new: addNew }) },
      contactsScopesFor(accountKind(a))),
  statement: (a: AccountInfo, id: string, from?: string, to?: string) => {
    const q = new URLSearchParams({ ...(from ? { from } : {}), ...(to ? { to } : {}) }).toString();
    return call<RtStatement>(a, `/contacts/${id}/statement${q ? `?${q}` : ""}`);
  },
  aged: (a: AccountInfo) => call<RtAged>(a, "/contacts/aged"),
};

/** Jobs, staff and timesheets (services/runtime/app/jobs.py). Money is integer pence; hours are 0.25 steps. */
/** Day planner (services/runtime/app/planner.py, routes_plan.py). Times carry their UK offset. */
export interface RtPlanItem {
  kind: "visit" | "travel" | "lunch" | "admin" | "existing";
  start: string;
  end: string;
  job_id: string | null;
  title: string;
  location: string | null;
}
export interface RtPlanConstraints {
  start?: string;
  end?: string;
  max_visits?: number;
}
export interface RtPlanRequest {
  date: string;
  constraints?: RtPlanConstraints;
  vat?: PlanVat | null;
  job_ids?: string[];
}
export interface RtPlan {
  date: string;
  plan: RtPlanItem[];
  rationale_md: string;
  warnings: string[];
  plan_hash: string;
  model: string | null;
  fallback_reason: string | null;
}
export interface RtMileageProposal {
  date: string;
  vehicle_id: string;
  job_id: string;
  from_district: string | null;
  to_district: string | null;
  miles: number | null;
  status: string;
  note: string;
}
export interface RtPlanApplied {
  date: string;
  plan_hash: string;
  event_ids: string[];
  created: { title: string; start: string; event_id: string; reused: boolean }[];
  already_applied: boolean;
  mileage_proposals: RtMileageProposal[];
}

export interface RtJobIn {
  name: string;
  customer_id: string | null;
  site_address: string | null;
  /** Hours on site for one visit; the day planner uses 2 h when unset. */
  estimate_hours?: number | null;
  status: "open" | "closed";
}
export interface RtJob extends RtJobIn {
  id: string;
  created_at: string;
}
export interface RtStaffIn {
  name: string;
  role: string;
  hourly_rate_pence: number;
  charge_rate_pence: number | null;
  active: boolean;
}
export interface RtStaff extends RtStaffIn {
  id: string;
}
export interface RtTimesheetIn {
  staff_id: string;
  job_id: string;
  date: string; // YYYY-MM-DD
  hours: number;
  note: string;
  billable: boolean;
}
export interface RtTimesheetEntry extends RtTimesheetIn {
  id: string;
  invoiced_in: string | null;
}
export interface RtJobSummary {
  job: RtJob;
  customer_name: string | null;
  hours: number;
  billable_hours: number;
  unbilled_hours: number;
  labour_cost_pence: number;
  billable_value_pence: number;
  invoiced_value_pence: number;
  unbilled_value_pence: number;
  materials_pence: number;
  purchases: { proposal_id: string; event_id: string; date: string; supplier: string | null; net_pence: number }[];
  margin_pence: number;
  by_staff: { staff_id: string; name: string; role: string; hours: number; labour_cost_pence: number; billable_value_pence: number }[];
  warnings: string[];
}
export interface RtInvoiceLine {
  description: string;
  qty: number;
  unit: string;
  unit_price_pence: number;
  net_pence: number;
  vat_code: string;
  staff_id: string;
  role: string;
  entry_ids: string[];
}
export interface RtInvoiceProposal {
  job_id: string;
  customer_id: string | null;
  lines: RtInvoiceLine[];
  entry_ids: string[];
  net_pence: number;
  warnings: string[];
}

/** Where "Create invoice from unbilled hours" leaves the proposed lines for the invoice form (sessionStorage). */
export const INVOICE_DRAFT_KEY = "accnomos.invoice-draft";
export const pence = (p: number) => gbp(p / 100);


/** Contacts (services/runtime/app/contacts.py). Pence are signed from the user's side: + they owe you, − you owe them. */
export type RtContactField = "name" | "kind" | "vrn" | "email" | "phone" | "address" | "default_category" | "default_vat_code";
export interface RtContact {
  id: string;
  kind: "customer" | "supplier" | "both";
  name: string;
  normalised_key: string;
  vrn: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  default_category: string | null;
  default_vat_code: string | null;
  source: "ledger" | "outlook" | "manual";
  aliases: string[];
  edited: string[];
  created_at: string;
  updated_at: string;
}
export interface RtContactTotals {
  documents: number;
  ytd_sales_net_pence: number;
  ytd_sales_vat_pence: number;
  ytd_purchases_net_pence: number;
  ytd_purchases_vat_pence: number;
  open_receivable_pence: number;
  open_payable_pence: number;
  balance_pence: number;
  last_activity: string | null;
}
export interface RtContactRow extends RtContact {
  totals: RtContactTotals;
}
export interface RtContactList {
  year_start: string;
  today: string;
  saved: boolean;
  contacts: RtContactRow[];
}
export interface RtStatementLine {
  date: string;
  details: string;
  reference: string | null;
  event_id: string | null;
  amount_pence: number;
  paid_pence: number;
  balance_pence: number;
}
export interface RtStatement {
  contact: RtContact;
  start: string | null;
  end: string | null;
  opening_balance_pence: number;
  closing_balance_pence: number;
  lines: RtStatementLine[];
}
export type RtAgedBucket = "0-30" | "31-60" | "61-90" | "90+";
export interface RtAgedRow {
  contact_id: string;
  name: string;
  buckets: Record<RtAgedBucket, number>;
  total_pence: number;
  documents: { event_id: string; date: string; reference: string | null; amount_pence: number; age_days: number; bucket: RtAgedBucket }[];
}
export interface RtAgedTable {
  rows: RtAgedRow[];
  buckets: Record<RtAgedBucket, number>;
  total_pence: number;
}
export interface RtAged {
  as_of: string;
  debtors: RtAgedTable;
  creditors: RtAgedTable;
}
export interface RtContactImport {
  read: number;
  matched: number;
  updated: number;
  added: number;
  skipped: number;
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
  kind: "open_review" | "open_vat" | "chase_supplier" | "plan_day" | "none"; // plan_day: arg = YYYY-MM-DD
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
export interface RtAskVoiceAnswer extends RtAskAnswer {
  transcript: string; // what Muse Voice heard; shown as the user's message
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
