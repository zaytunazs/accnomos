"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { aiHeaders, loadAiConfig, RUNTIME_URL, type AiConfig } from "./ai-config";
import type { PlanVat } from "./business";
import { vatQuery } from "./vat-period";
import {
  accountKind,
  CALENDAR_READ_SCOPES,
  CALENDAR_SCOPES,
  contactsScopesFor,
  getToken,
  isPersonalAccount,
  mailDraftScopesFor,
  mailScopesFor,
  mailSendScopesFor,
  storageScopesFor,
} from "./msal";

/** `path?query`, or just `path` when the query is empty. */
const withQuery = (path: string, query: string) => (query ? `${path}?${query}` : path);

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
  /** What code changed in the model's reading before the checks, one plain note each (never silent). */
  repaired_by_code?: string[];
  source_path?: string;
  /** Where the document is filed now, relative to the books folder (read through Graph for the preview). */
  file_path?: string | null;
  source_name?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
  event_id?: string | null;
  autopilot?: { auto_approve: boolean; reasons: string[]; supplier_key: string | null } | null;
  /** Business vehicle this cost is tagged to (pre-filled when there is exactly one). */
  vehicle_id?: string | null;
  /** Set on mileage allowance claims, which code builds: approve them as they are. */
  mileage_claim?: { tax_year: string; period: string; covers_to: string; entry_ids: string[]; miles: number } | null;
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
/** Settings › Autopilot level; L1 when nothing (or something unknown) is saved. */
export function autopilotLevel(): "L0" | "L1" | "L2" {
  try {
    const v = window.localStorage.getItem(AUTOPILOT_LEVEL_KEY);
    return v === "L0" || v === "L2" ? v : "L1";
  } catch {
    return "L1";
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
  if (!res.ok) throw new Error(await errorDetail(res, `${init.method ?? "GET"} ${path}`));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

/** The first event of a streamed answer: what code shows before the model has written a word. */
export type RtAskPreview = Pick<RtAskAnswer, "key_numbers" | "citations" | "suggested_actions" | "model" | "period">;

/**
 * POST /books/ask?stream=1 (server-sent events): `onStart` gets code's key numbers and citations at once,
 * `onToken` the explanation as the model writes it (unchecked), and the promise resolves to the checked answer,
 * the same object the plain call returns. Throws if the stream fails or ends early, so the caller can fall
 * back to `runtime.ask`.
 */
export async function askStream(
  account: AccountInfo,
  question: string,
  period: RtAskPeriod | null,
  history: RtAskTurn[],
  on: { onStart?: (p: RtAskPreview) => void; onToken?: (text: string) => void },
): Promise<RtAskAnswer> {
  const query = [vatQuery(), "stream=1"].filter(Boolean).join("&");
  const headers = { ...(await runtimeHeaders(account)), "Content-Type": "application/json", Accept: "text/event-stream" };
  const res = await fetch(`${RUNTIME_URL}/books/ask?${query}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question, period: period ?? null, history: history.slice(-6) }),
  });
  if (!res.ok) throw new Error(await errorDetail(res, "POST /books/ask?stream=1"));
  if (!res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) throw new Error("No event stream");
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) throw new Error("The answer stream ended before the checked answer");
    buffer += value;
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload: unknown = JSON.parse(data);
      if (event === "start") on.onStart?.(payload as RtAskPreview);
      else if (event === "token") on.onToken?.((payload as { text: string }).text);
      else if (event === "answer") {
        void reader.cancel();
        return payload as RtAskAnswer;
      }
    }
  }
}

export interface RtAiTest {
  ok: boolean;
  mode: string;
  model?: string | null;
  detail: string;
}

/** POST /ai/test: does this AI config answer? No sign-in needed; nothing is saved. */
export async function runtimeAiTest(cfg: AiConfig): Promise<RtAiTest> {
  const res = await fetch(`${RUNTIME_URL}/ai/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...aiHeaders(cfg) },
    body: JSON.stringify({ mode: cfg.mode, base_url: cfg.baseUrl, model: cfg.model }),
  });
  if (!res.ok) return { ok: false, mode: cfg.mode, detail: `runtime returned ${res.status}` };
  return (await res.json()) as RtAiTest;
}

/** GET /health: no sign-in needed. Null when the runtime does not answer. */
export async function runtimeHealth(): Promise<{ ok: boolean; voice?: boolean } | null> {
  try {
    const res = await fetch(`${RUNTIME_URL}/health`);
    return res.ok ? ((await res.json()) as { ok: boolean; voice?: boolean }) : null;
  } catch {
    return null;
  }
}

export const runtime = {
  scan: (a: AccountInfo) =>
    // The saved VAT settings set the period that scanned dates are checked against (DATE_IN_PERIOD warning).
    call<{ proposals: RtProposal[]; errors: { path: string; error: string }[] }>(a, withQuery("/books/scan", vatQuery()), {
      method: "POST",
      headers: autopilotOn() ? {} : { "X-Autopilot": "off" },
    }),
  proposals: (a: AccountInfo, status?: string) => call<RtProposal[]>(a, `/books/proposals${status ? `?status=${status}` : ""}`),
  proposal: (a: AccountInfo, id: string) => call<RtProposal>(a, `/books/proposals/${id}`),
  /** `edits.job_id` tags a purchase to a job (its net then counts as a job cost). */
  approve: (a: AccountInfo, id: string, body: { edits?: Record<string, unknown>; remember?: boolean }) =>
    call<RtProposal>(a, `/books/proposals/${id}/approve`, { method: "POST", body: JSON.stringify(body) }),
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
    call<RtAskAnswer>(a, withQuery("/books/ask", vatQuery()), {
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
    return call<RtAskVoiceAnswer>(a, withQuery("/books/ask/voice", vatQuery()), { method: "POST", body: form });
  },
  /** POST /actions/approve: run a proposed action exactly as Ask returned it (signed; refused if changed or expired). */
  approveAction: (a: AccountInfo, action: RtProposedAction) =>
    call<RtActionResult>(a, "/actions/approve", { method: "POST", body: JSON.stringify({ action }) }),
  /** POST /actions/reject: nothing happens except a line in the actions audit log. */
  rejectAction: (a: AccountInfo, action: RtProposedAction, reason?: string) =>
    call<{ action_id: string; status: "rejected" }>(a, "/actions/reject", {
      method: "POST",
      body: JSON.stringify({ action, reason: reason ?? null }),
    }),
  mailScan: (a: AccountInfo, body: { since_days?: number; dry_run?: boolean }) =>
    call<RtMailScan>(a, "/mail/scan", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /** POST /mail/triage: reads Inbox previews (Mail.Read) and changes nothing in the mailbox. */
  mailTriage: (a: AccountInfo, body: { since_days?: number; max_threads?: number } = {}) =>
    call<RtTriage>(a, "/mail/triage", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /** POST /mail/draft-reply: saves an Outlook draft, never sends. Asks for Mail.ReadWrite only now. */
  draftReply: (a: AccountInfo, messageId: string, body: string) =>
    call<RtDraftReply>(a, "/mail/draft-reply", { method: "POST", body: JSON.stringify({ message_id: messageId, body }) },
      mailDraftScopesFor(accountKind(a))),
  /** To-dos in _System/Todos/todos.json. */
  todos: (a: AccountInfo) => call<RtTodo[]>(a, "/todos"),
  addTodo: (a: AccountInfo, todo: RtTodoIn) => call<RtTodo>(a, "/todos", { method: "POST", body: JSON.stringify(todo) }),
  deleteTodo: (a: AccountInfo, id: string) => call<RtTodo>(a, `/todos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** POST /books/rebuild: regenerate Books.xlsx from the event files now. */
  rebuild: (a: AccountInfo) => call<RtRebuild>(a, "/books/rebuild", { method: "POST" }),
  /** GET /books/layout: renames old-named folders (once) and lists old/new pairs left side by side. */
  layout: (a: AccountInfo) => call<RtLayout>(a, "/books/layout"),
  /** GET /books/deadlines?stagger=1 | start_month=5 | months=1 (see lib/business.ts deadlinesQuery). */
  deadlines: (a: AccountInfo, query: string) => call<RtDeadlines>(a, `/books/deadlines?${query}`),
  /** GET /books/dashboard: the Home tiles in one call (same VAT query as deadlines, plus `today`). */
  dashboard: (a: AccountInfo, query: string) => call<RtDashboard>(a, `/books/dashboard?${query}`),

  /** GET /books/vat/periods: the current VAT period and the 8 before it, by the saved VAT settings. */
  vatPeriods: (a: AccountInfo) => call<RtVatPeriods>(a, withQuery("/books/vat/periods", vatQuery())),

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
  deleteJob: (a: AccountInfo, id: string) => call<void>(a, `/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** Proposed lines from unbilled billable hours; marks nothing. */
  jobInvoiceLines: (a: AccountInfo, id: string) =>
    call<RtInvoiceProposal>(a, `/jobs/${encodeURIComponent(id)}/invoice-lines`, { method: "POST" }),
  staff: (a: AccountInfo) => call<RtStaff[]>(a, "/staff"),
  createStaff: (a: AccountInfo, body: RtStaffIn) => call<RtStaff>(a, "/staff", { method: "POST", body: JSON.stringify(body) }),
  updateStaff: (a: AccountInfo, id: string, body: RtStaffIn) =>
    call<RtStaff>(a, `/staff/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteStaff: (a: AccountInfo, id: string) => call<void>(a, `/staff/${encodeURIComponent(id)}`, { method: "DELETE" }),
  timesheets: (a: AccountInfo, jobId: string) => call<RtTimesheetEntry[]>(a, `/timesheets?job_id=${encodeURIComponent(jobId)}`),
  addTimesheet: (a: AccountInfo, body: RtTimesheetIn) =>
    call<RtTimesheetEntry>(a, "/timesheets", { method: "POST", body: JSON.stringify(body) }),
  updateTimesheet: (a: AccountInfo, id: string, patch: Partial<RtTimesheetIn>) =>
    call<RtTimesheetEntry>(a, `/timesheets/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(patch) }),
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
  /** /books/bank/* (services/runtime/app/routes_bank.py): statements, matches and unmatched lines. */
  bank: {
    /** POST /books/bank/import: multipart upload; the same file twice is a no-op (sha256). */
    upload: (a: AccountInfo, file: File) => {
      const form = new FormData();
      form.append("file", file, file.name);
      return call<RtBankImport>(a, "/books/bank/import", { method: "POST", body: form });
    },
    statements: (a: AccountInfo) => call<RtBankStatement[]>(a, "/books/bank/statements"),
    lines: (a: AccountInfo, status?: RtBankLineStatus) =>
      call<RtBankLine[]>(a, `/books/bank/lines${status ? `?status=${status}` : ""}`),
    suggestions: (a: AccountInfo) => call<RtBankSuggestion[]>(a, "/books/bank/suggestions"),
    unmatched: (a: AccountInfo) => call<RtUnmatchedLine[]>(a, "/books/bank/unmatched"),
    summary: (a: AccountInfo) => call<RtBankSummary>(a, "/books/bank/summary"),
    confirm: (a: AccountInfo, lineId: string, eventIds: string[]) =>
      call<RtBankLine>(a, `/books/bank/lines/${lineId}/match`, { method: "POST", body: JSON.stringify({ event_ids: eventIds }) }),
    /** Reopen a matched, transfer or ignored line. */
    reopen: (a: AccountInfo, lineId: string) => call<RtBankLine>(a, `/books/bank/lines/${lineId}/unmatch`, { method: "POST" }),
    transfer: (a: AccountInfo, lineId: string) => call<RtBankLine>(a, `/books/bank/lines/${lineId}/transfer`, { method: "POST" }),
    ignore: (a: AccountInfo, lineId: string) => call<RtBankLine>(a, `/books/bank/lines/${lineId}/ignore`, { method: "POST" }),
    expenseProposal: (a: AccountInfo, lineId: string) =>
      call<RtProposal>(a, `/books/bank/lines/${lineId}/expense-proposal`, { method: "POST" }),
  },
  vehicles: (a: AccountInfo) => call<RtVehicle[]>(a, "/vehicles"),
  addVehicle: (a: AccountInfo, v: Omit<RtVehicle, "id">) =>
    call<RtVehicle>(a, "/vehicles", { method: "POST", body: JSON.stringify(v) }),
  updateVehicle: (a: AccountInfo, id: string, patch: Partial<Omit<RtVehicle, "id">>) =>
    call<RtVehicle>(a, `/vehicles/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteVehicle: (a: AccountInfo, id: string) => call<RtVehicle>(a, `/vehicles/${id}`, { method: "DELETE" }),
  mileage: (a: AccountInfo, taxYear: string) => call<RtMileageEntry[]>(a, `/mileage?tax_year=${taxYear}`),
  addMileage: (a: AccountInfo, e: Omit<RtMileageEntry, "id" | "source">) =>
    call<RtMileageEntry>(a, "/mileage", { method: "POST", body: JSON.stringify(e) }),
  updateMileage: (a: AccountInfo, id: string, patch: Partial<Omit<RtMileageEntry, "id" | "source">>) =>
    call<RtMileageEntry>(a, `/mileage/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteMileage: (a: AccountInfo, id: string) => call<RtMileageEntry>(a, `/mileage/${id}`, { method: "DELETE" }),
  mileageSummary: (a: AccountInfo, taxYear: string) => call<RtMileageSummary>(a, `/mileage/summary?tax_year=${taxYear}`),
  /** POST /mileage/propose-allowance: the quarter's allowance as a proposal in Review (one per quarter). */
  proposeAllowance: (a: AccountInfo, taxYear: string, period: string) =>
    call<{ proposal: RtProposal; created: boolean }>(a, `/mileage/propose-allowance?tax_year=${taxYear}&period=${period}`, {
      method: "POST",
    }),
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

  /** /payroll/runs (services/runtime/app/routes_payroll.py): estimates for the payroll provider; only confirm posts. */
  payrollRuns: (a: AccountInfo) => call<RtPayRunList>(a, "/payroll/runs"),
  preparePayRun: (a: AccountInfo, period: string, payDate?: string | null) =>
    call<RtPayRun>(a, "/payroll/runs/prepare", { method: "POST", body: JSON.stringify({ period, pay_date: payDate ?? null }) }),
  editPayRun: (a: AccountInfo, period: string, lines: RtPayLineEdit[], payDate?: string | null) =>
    call<RtPayRun>(a, `/payroll/runs/${period}`, { method: "PUT", body: JSON.stringify({ lines, pay_date: payDate ?? null }) }),
  /** Saves 05 Payroll/<period>.csv in OneDrive and returns the CSV text. */
  exportPayRun: (a: AccountInfo, period: string) =>
    call<{ path: string; csv: string; estimate: string }>(a, `/payroll/runs/${period}/export`, { method: "POST" }),
  /** The figures your payroll provider calculated, not the estimate. */
  confirmPayRun: (a: AccountInfo, period: string, actualGrossPence: number, actualErNiPence: number) =>
    call<RtPayRun>(a, `/payroll/runs/${period}/confirm`, {
      method: "POST",
      body: JSON.stringify({ actual_gross_pence: actualGrossPence, actual_er_ni_pence: actualErNiPence }),
    }),
  reopenPayRun: (a: AccountInfo, period: string) => call<RtPayRun>(a, `/payroll/runs/${period}/reopen`, { method: "POST" }),

  /** /reports/* (services/runtime/app/routes_reports.py): by code from the ledger; only export writes (07 Reports). */
  reports: {
    /** No span = the VAT period we are in now, by the saved VAT settings. */
    pl: (a: AccountInfo, span?: { start: string; end: string } | null) =>
      call<RtProfitAndLoss>(a, withQuery("/reports/pl", [vatQuery(), span ? `from=${span.start}&to=${span.end}` : ""].filter(Boolean).join("&"))),
    aged: (a: AccountInfo) => call<RtAgedReport>(a, "/reports/aged"),
    vat: (a: AccountInfo, periods = 4) => call<RtVatSummary>(a, withQuery("/reports/vat", [vatQuery(), `periods=${periods}`].filter(Boolean).join("&"))),
    trend: (a: AccountInfo) => call<RtTrend>(a, "/reports/trend"),
    /** Saves 07 Reports/<yyyy-mm-dd>-<name>.xlsx in OneDrive; posts nothing. */
    export: (a: AccountInfo, body: { report?: RtReportKind; from?: string; to?: string; periods?: number }) =>
      call<RtReportExport>(a, withQuery("/reports/export", vatQuery()), { method: "POST", body: JSON.stringify(body) }),
  },
};

/** Reports (services/runtime/app/reports.py). Pence throughout; VAT boxes 6 and 7 whole pounds. */
export interface RtPlSection {
  rows: { account: string; amount_pence: number }[];
  total_pence: number;
}
export interface RtProfitAndLoss {
  start: string;
  end: string;
  label: string;
  basis: string; // "As approved: …"
  sales: RtPlSection;
  cost_of_sales: RtPlSection;
  gross_profit_pence: number;
  overheads: RtPlSection;
  net_profit_pence: number; // negative = a loss
  entries: number;
  sample: boolean;
}
export interface RtAgedReport extends RtAged {
  sample: boolean;
}
export interface RtVatSummaryPeriod {
  period: string;
  start: string;
  end: string;
  label: string;
  vat_on_sales_pence: number;
  vat_reclaimed_pence: number;
  net_vat_pence: number; // positive to pay, negative to reclaim
  sales_ex_vat_pounds: number;
  purchases_ex_vat_pounds: number;
  entries: number;
  warnings: string[];
}
export interface RtVatSummary {
  periods: RtVatSummaryPeriod[]; // oldest first
  total_net_vat_pence: number;
  sample: boolean;
}
export interface RtTrendMonth {
  month: string; // "2026-10"
  label: string; // "Oct 2026"
  start: string;
  end: string;
  sales_pence: number;
  purchases_pence: number; // cost of sales + overheads
  net_pence: number;
}
export interface RtTrend {
  months: RtTrendMonth[]; // oldest first
  sample: boolean;
}
export type RtReportKind = "pl" | "aged" | "vat" | "trend" | "all";
export interface RtReportExport {
  path: string;
  name: string;
  size: number;
  web_url: string | null;
  sample: boolean;
  sheets: string[];
}

/** Pay runs (services/runtime/app/payroll.py). Pence throughout; every est_* figure is an estimate. */
export interface RtPayLine {
  staff_id: string;
  hours: number;
  rate_pence: number;
  gross_pence: number;
  est_paye_pence: number;
  est_ee_ni_pence: number;
  est_er_ni_pence: number;
  est_net_pence: number;
  notes: string;
}
export interface RtPayLineEdit {
  staff_id: string;
  hours: number;
  rate_pence: number;
  notes: string;
}
export interface RtPayRun {
  period_start: string;
  period_end: string;
  pay_date: string;
  lines: RtPayLine[];
  status: "draft" | "confirmed";
  confirmed_gross_pence: number | null;
  confirmed_er_ni_pence: number | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  event_ids: string[];
  undone_event_ids: string[];
  warnings: string[];
  estimate: string;
  limits: string[];
}
export interface RtPayRunList {
  runs: RtPayRun[];
  estimate: string;
  limits: string[];
  tax_year: string;
  source_url: string;
}

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

/** Jobs, staff and timesheets (services/runtime/app/jobs.py). Money is integer pence; hours are 0.25 steps. */
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
/** A line proposed from timesheets (jobs); the Invoices feature's own line type is RtInvoiceLine below. */
export interface RtJobInvoiceLine {
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
  lines: RtJobInvoiceLine[];
  entry_ids: string[];
  net_pence: number;
  warnings: string[];
}

/** Where "Invoice these hours" leaves the proposed lines for /invoices/new?from=job (sessionStorage). */
export const INVOICE_DRAFT_KEY = "accnomos.invoice-draft";
export interface JobInvoiceDraft {
  proposal: RtInvoiceProposal;
  job_name: string;
  customer_name: string | null;
}
export const pence = (p: number) => gbp(p / 100);


/** Contacts (services/runtime/app/contacts.py). Pence are signed from the user's side: + they owe you, − you owe them. */
export type RtContactField = "name" | "kind" | "vrn" | "email" | "phone" | "address" | "default_category" | "default_vat_code" | "vat_status";
/** Whether a supplier charges VAT, as the books remember it: learnt on approval, editable on Contacts. */
export type RtVatStatus = "registered" | "not_registered" | "unknown";
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
  vat_status?: RtVatStatus; // absent from runtimes before 27 Oct 2026: read as "unknown"
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

/**
 * FastAPI errors are {"detail": "..."}; show that sentence, not the JSON. The HTTP status and the
 * runtime's correlation id travel in a machine-readable suffix so the shared error states
 * (components/States.tsx) can tell an expired sign-in (401) from a server fault (5xx) later.
 * Calls, headers, payloads and storage keys are unchanged — only this error text.
 */
async function errorDetail(res: Response, what: string): Promise<string> {
  const text = await res.text();
  let detail: unknown;
  let correlation: unknown;
  try {
    const body = JSON.parse(text) as { detail?: unknown; correlation_id?: unknown };
    detail = body.detail;
    correlation = body.correlation_id;
  } catch {
    /* not JSON */
  }
  const ref = typeof correlation === "string" && correlation ? ` · ref ${correlation}` : "";
  if (typeof detail === "string") return `${detail} (status ${res.status}${ref})`;
  return `Could not ${what} (${res.status}): ${text.slice(0, 200)}${ref}`;
}

/** /books/bank/* wire types. Amounts are signed pence: money out is negative. Dates are YYYY-MM-DD. */
export type RtBankLineStatus = "unmatched" | "matched" | "suggested" | "transfer" | "ignored";

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
  timesheet_entry_ids?: string[]; // the job hours this line bills; marked invoiced when the invoice is sent
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
  job_id?: string | null;
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
  job_id: string | null;
  timesheets_marked: boolean;
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
  /** Settings › Business. False: receipts never need a supplier's VAT number (nothing is reclaimed). A VRN means true. */
  vat_registered?: boolean;
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
  balance_pence: number | null;
  source_file: string;
  matched_event_id: string | null;
  matched_event_ids: string[];
  status: RtBankLineStatus;
  proposal_id: string | null;
}
export interface RtBankImport {
  sha256: string;
  filed_path: string | null;
  lines: number;
  new_lines: number;
  duplicate_file: boolean;
  bank: string;
}
export interface RtBankStatement {
  path: string;
  bank: string;
  first_date: string;
  last_date: string;
  lines: number;
  resolved: number;
  money_in_pence: number;
  money_out_pence: number;
}
export interface RtBankSuggestion {
  line_id: string;
  event_id: string;
  event_ids: string[];
  score: number;
  kind: "exact" | "suggested";
  reasons: string[];
  line: RtBankLine;
  events: { id: string; date: string; counterparty: string | null; amount_pence: number }[];
}
export type RtUnmatchedAction = "create_expense_proposal" | "mark_transfer" | "ignore";
export interface RtUnmatchedLine {
  line: RtBankLine;
  suggested: { action: RtUnmatchedAction; reason: string };
  /** Status of the expense proposal made from this line, if any; after "rejected" a new one may be made. */
  proposal_status: "proposed" | "needs_a_look" | "posted" | "rejected" | null;
}
export interface RtBankSummary {
  total: number;
  matched: number;
  suggested: number;
  unmatched: number;
  transfer: number;
  ignored: number;
  reconciled_to: string | null;
}

/** Vehicles and mileage (services/runtime/app/mileage.py). Amounts in pence, miles in 0.1 steps. */
export type RtVehicleKind = "car" | "van" | "motorcycle" | "bicycle";
export interface RtVehicle {
  id: string;
  name: string;
  registration: string | null;
  kind: RtVehicleKind;
  owned_by: "business" | "personal";
  active: boolean;
}
export interface RtMileageEntry {
  id: string;
  vehicle_id: string;
  date: string;
  from: string;
  to: string;
  miles: number;
  purpose: string;
  job_id: string | null;
  source: "manual" | "proposal";
}
export interface RtVehicleSummary {
  vehicle_id: string;
  name: string;
  registration: string | null;
  kind: RtVehicleKind;
  owned_by: "business" | "personal";
  active: boolean;
  miles: number;
  journeys: number;
  allowance_pence: number;
  cost_pence: number;
  cost_entries: number;
  pence_per_mile: number | null;
}
export interface RtMileageQuarter {
  period: string;
  start: string;
  end: string;
  miles: number;
  allowance_pence: number;
  claimed_pence: number;
  unclaimed_pence: number;
  waiting_claim_id: string | null;
}
export interface RtMileageSummary {
  tax_year: string;
  start: string;
  end: string;
  vehicles: RtVehicleSummary[];
  car_van_miles: number;
  threshold_miles: number;
  threshold_crossed_on: string | null;
  allowance_pence: number;
  claimed_pence: number;
  quarters: RtMileageQuarter[];
  locked_until: string | null;
  rates: { kind: RtVehicleKind; first_pence: number; after_pence: number; threshold_miles: number | null }[];
  notes: string[];
  status: "unmatched" | "matched" | "suggested";
}

/** GET /books/layout (services/runtime/app/layout.py). */
export interface RtLayout {
  moved: { old: string; new: string }[];
  conflicts: { old: string; new: string; old_is_empty: boolean }[];
  warning: string | null;
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

/** GET /books/dashboard (services/runtime/app/dashboard.py). Pence; a null section could not be worked out. */
export interface RtOwed {
  total_pence: number;
  documents: number;
  oldest_days: number | null;
}
export interface RtDashboardRun {
  at: string;
  summary: string | null;
}
export interface RtDashboard {
  today: string;
  cash: {
    balance_pence: number | null; // closing balance on the latest statement with a matched line
    as_of: string | null;
    bank: string | null;
    statement: string | null;
    reconciled_to: string | null;
  } | null;
  owed_to_you: (RtOwed & { overdue: number | null; overdue_pence: number | null; most_overdue_days: number | null }) | null;
  owed_by_you: RtOwed | null;
  vat: RtDeadlines | null;
  attention: {
    proposed: number;
    needs_a_look: number;
    unmatched_bank_lines: number;
    overdue_invoices: number | null;
    total: number;
  } | null;
  activity: { at: string; actor: string; action: string; text: string; tone: "ok" | "warn" }[];
  runs: Record<"scan" | "autopilot" | "intake" | "triage", RtDashboardRun | null>;
  unavailable: string[];
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
  proposed_action?: RtProposedAction | null; // an instruction: show the card; nothing happens until Approve
  clarification?: RtClarification | null; // an instruction Ask needs one more detail for
}
/** Proposed actions (services/runtime/app/actions.py). Kept by the app only; post back unchanged to approve. */
export type RtActionKind = "create_invoice" | "chase_invoice" | "log_mileage" | "log_timesheet";
export interface RtProposedAction {
  id: string;
  kind: RtActionKind;
  summary_md: string;
  /** What code resolved and priced. Shape per kind: see RtInvoicePreview etc. Money in pence. */
  preview: Record<string, unknown>;
  confirm_text: string;
  created_at: string;
  expires_at: string;
  signature: string;
}
export interface RtInvoicePreview {
  customer: { contact_id: string; name: string; email: string | null; address: string | null; vrn: string | null };
  issue_date: string;
  due_date: string;
  terms_days: number;
  lines: { description: string; quantity: string; unit_price_pence: number; vat_code: string; vat_rate: number; net_pence: number; vat_pence: number }[];
  vat_summary: { vat_code: string; vat_rate: number; net_pence: number; vat_pence: number }[];
  net_pence: number;
  vat_pence: number;
  total_pence: number;
  send: boolean;
  send_to: string | null;
  warnings: string[];
}
export interface RtChasePreview {
  invoice: string;
  customer: string;
  total_pence: number;
  due_date: string;
  days_overdue: number;
  to: string;
  subject: string;
  body: string;
  warnings: string[];
}
export interface RtTimesheetPreview {
  staff_name: string;
  job_name: string;
  date: string;
  hours: string;
  note: string;
  warnings: string[];
}
export interface RtMileagePreview {
  vehicle_name: string;
  date: string;
  from: string;
  to: string;
  miles: string;
  job_name: string | null;
  warnings: string[];
}
export interface RtClarification {
  kind: RtActionKind;
  field: string;
  question_md: string;
  candidates: string[];
  ref: string | null; // the user's words for the thing, replaced by the picked candidate when re-asking
}
export interface RtActionResult {
  action_id: string;
  kind: RtActionKind;
  status: "done" | "already_done";
  summary_md: string;
  result: Record<string, unknown>;
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

/** POST /mail/triage (services/runtime/app/triage.py). */
export type RtTriageCategory = "customer" | "supplier" | "hmrc" | "accountant" | "other";
export interface RtTriageTodo {
  text: string;
  due: string | null;
}
export interface RtTriageThread {
  conversation_id: string;
  message_id: string;
  subject: string;
  from_name: string;
  from_address: string;
  received_at: string;
  unread: boolean;
  message_count: number;
  web_link: string | null;
  category: RtTriageCategory;
  summary: string;
  needs_reply: boolean;
  suggested_reply: string | null;
  todos: RtTriageTodo[];
  fallback_reason: string | null;
}
export interface RtTriage {
  since_days: number;
  scanned: number;
  skipped: Record<string, number>;
  threads: RtTriageThread[];
  model: string | null;
  generated_at: string;
}
export interface RtDraftReply {
  draft_id: string;
  web_link: string | null;
}
/** /todos (services/runtime/app/todos.py). */
export interface RtTodoIn {
  text: string;
  due?: string | null;
  source?: { kind?: "mail"; message_id?: string | null; subject?: string; web_link?: string | null } | null;
}
export interface RtTodo extends RtTodoIn {
  id: string;
  created_at: string;
  created_by: string;
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
  period: string; // "2026-Q4" (quarterly) or "2026-11" (monthly)
  label: string; // "Oct–Dec 2026"
  current: boolean;
  submitted: boolean; // a relay submission receipt is saved in 06 VAT returns
  can_submit: boolean; // current or previous period and not yet submitted
  boxes: RtVatBox[];
  event_ids: string[];
  warnings: string[];
  events_in_period: number;
  hmrc_body: Record<string, unknown>;
}

/** GET /books/vat/periods (services/runtime/app/routes_vat.py). */
export interface RtVatPeriod {
  period: string;
  start: string;
  end: string;
  label: string;
  current: boolean;
  deadline: string;
  status: "open" | "submitted" | "none";
  hmrc_period_key: string | null;
  entries: number;
  can_submit: boolean;
}
export interface RtVatPeriods {
  today: string;
  months: number;
  start_month: number;
  periods: RtVatPeriod[]; // current first, then the 8 before it
  status_source: string;
}

let liveVat: { key: string; promise: Promise<RtVatView> } | null = null;

/** The live return for `period` (null = the current one), fetched once per page per account and period
 *  (LiveVat and ConnectHmrc both read it). */
export function fetchLiveVat(account: AccountInfo, period: string | null = null): Promise<RtVatView> {
  const query = [vatQuery(), period ? `period=${encodeURIComponent(period)}` : ""].filter(Boolean).join("&");
  const key = `${account.homeAccountId}?${query}`;
  if (!liveVat || liveVat.key !== key) {
    const promise = call<RtVatView>(account, withQuery("/books/vat", query));
    promise.catch(() => {
      if (liveVat?.promise === promise) liveVat = null; // let a later mount retry
    });
    liveVat = { key, promise };
  }
  return liveVat.promise;
}

export const gbp = (n: number) => `£${n.toFixed(2)}`;
export const ukDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
