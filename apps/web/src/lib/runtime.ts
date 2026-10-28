"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { aiHeaders, loadAiConfig, RUNTIME_URL, type AiConfig } from "./ai-config";
import type { PlanVat } from "./business";
import { vatQuery } from "./vat-period";
import { DEMO_HEADER, demoSession } from "./demo";
import {
  clientHeaders,
  CLIENT_SCOPES,
  getClientContext,
  PORTAL_SCOPES,
  SHARE_SCOPES,
  type RtAccountantSettings,
  type RtClientProfile,
  type RtInvitation,
  type RtPortal,
  type RtQuery,
  type QuerySubjectKind,
} from "./accountant";
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
  original_invoice_number?: string | null; // a supplier credit note: the bill it credits, if printed
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
  /** Which provider of the server's chain read it (services/runtime/app/ai/chain.py). */
  served_by?: RtServedBy | null;
  /** How the photo was cropped before extraction; "none" = original used. Chip: crop.note. */
  crop?: { method: "sam" | "code" | "none"; box: [number, number, number, number] | null; note: string } | null;
  verification?: RtVerification | null;
  /** What code changed in the model's reading before the checks, one plain note each (never silent). */
  repaired_by_code?: string[];
  source_path?: string;
  /** Where the document is filed now, relative to the books folder (read through Graph for the preview). */
  file_path?: string | null;
  source_name?: string | null;
  source_mailbox?: string | null; // the mailbox Outlook intake copied it from
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
/** Who served an AI result: provider (modal | meta | spark | baseten | local | key | test), model, time. */
export interface RtServedBy {
  provider: string;
  model: string;
  latency_ms: number;
  fell_back_from: string[];
}

export interface RtVerification {
  served_by?: RtServedBy | null;
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
export async function runtimeHeaders(
  account: AccountInfo,
  extraScopes: string[] = [],
  opts: { own?: boolean } = {},
): Promise<Record<string, string>> {
  const ai = loadAiConfig();
  const demo = demoSession();
  if (demo) {
    // The demo sandbox (lib/demo.ts): the session id instead of a Graph token; the runtime answers from memory.
    return {
      [DEMO_HEADER]: demo.session,
      "X-Account-Kind": "personal",
      "X-User": demo.user,
      "X-Business-Name": demo.business,
      ...(ai ? aiHeaders(ai) : {}),
    };
  }
  // An accountant inside a client's books (lib/accountant.ts): the token must reach another person's drive.
  const client = opts.own ? null : getClientContext();
  const base = client ? CLIENT_SCOPES : storageScopesFor(account);
  const token = await getToken([...base, ...extraScopes]);
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
    ...(business && !client ? { "X-Business-Name": business } : {}),
    ...(ai ? aiHeaders(ai) : {}),
    ...clientHeaders(client),
  };
}

async function call<T>(
  account: AccountInfo,
  path: string,
  init: RequestInit = {},
  extraScopes: string[] = [],
  opts: { own?: boolean } = {},
): Promise<T> {
  const json = typeof init.body === "string"; // FormData sets its own multipart Content-Type
  const headers = { ...(await runtimeHeaders(account, extraScopes, opts)), ...(json ? { "Content-Type": "application/json" } : {}) };
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

/** POST /books/undo/{event_id} (services/runtime/app/routes_books.py): a reversing entry; the proposal goes back to Review. */
export interface RtUndoResult {
  proposal: RtProposal | null;
  /** True when the entry's VAT period was already submitted, so the correction is dated today. */
  dated_today: boolean;
  /** "Your return for Jul–Sep 2026 was already submitted, so this correction goes in Oct–Dec 2026." */
  reason: string | null;
  submitted_period: string | null;
  current_period: string | null;
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
export async function runtimeHealth(): Promise<{ ok: boolean; voice?: boolean; demo?: { enabled: boolean; ready: boolean } } | null> {
  try {
    const res = await fetch(`${RUNTIME_URL}/health`);
    return res.ok ? ((await res.json()) as { ok: boolean; voice?: boolean; demo?: { enabled: boolean; ready: boolean } }) : null;
  } catch {
    return null;
  }
}

/** GET/PUT /profile (services/runtime/app/profile.py): what these books are, from `_System/profile.json`. */
export type RtProfileKind = "company" | "sole_trader" | "personal";
export interface RtProfileSettings {
  company_number?: string | null;
  vat_number?: string | null;
  vat_registered?: boolean;
  utr?: string | null;
  accounting_period_start?: string;
}
export interface RtLinkedAccount {
  username: string;
  name?: string;
  kind?: RtProfileKind | null;
}
export interface RtProfile {
  name: string;
  kind: RtProfileKind;
  settings: RtProfileSettings;
  linked: RtLinkedAccount[];
  updated_at: string | null;
  /** False: no profile.json yet; these are the defaults (a VAT-registered company). */
  exists: boolean;
  /** What these books have; the nav hides the rest (personal: no vat, invoices, payroll). */
  features: string[];
}

export const runtime = {
  /** GET /profile: this account's profile (its own books). */
  profile: (a: AccountInfo) => call<RtProfile>(a, "/profile"),
  /** PUT /profile: save it whole; `linked` left out keeps the saved list. */
  saveProfile: (
    a: AccountInfo,
    body: { name: string; kind: RtProfileKind; settings?: RtProfileSettings; linked?: RtLinkedAccount[] },
  ) => call<RtProfile>(a, "/profile", { method: "PUT", body: JSON.stringify(body) }),
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
    call<RtUndoResult>(a, `/books/undo/${eventId}`, { method: "POST" }),
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
  /** POST /mail/scan for the signed-in mailbox (its Mail.Read rides on the one Graph token). */
  mailScan: (a: AccountInfo, body: { since_days?: number; dry_run?: boolean }) =>
    call<RtMailScan>(a, "/mail/scan", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /**
   * POST /mail/scan for one linked mailbox: its own token goes in X-Mailbox-Token, for this request only (one
   * mailbox per request; the runtime keeps no token). The Graph token still writes the books.
   */
  mailScanLinked: (a: AccountInfo, mailboxId: string, mailboxToken: string, body: { since_days?: number; dry_run?: boolean }) =>
    call<RtMailScan>(a, "/mail/scan", {
      method: "POST",
      body: JSON.stringify({ ...body, mailbox: mailboxId }),
      headers: { "X-Mailbox-Token": mailboxToken },
    }),
  /** _System/mail/mailboxes.json (services/runtime/app/mailboxes.py): addresses and settings, never tokens. */
  mailboxes: (a: AccountInfo) => call<{ mailboxes: RtMailbox[] }>(a, "/mail/mailboxes").then((r) => r.mailboxes),
  addMailbox: (a: AccountInfo, box: { address: string; kind: "microsoft" | "shared" }) =>
    call<RtMailbox>(a, "/mail/mailboxes", { method: "POST", body: JSON.stringify(box) }),
  updateMailbox: (a: AccountInfo, id: string, change: { folder?: string; allow_senders?: string[]; deny_senders?: string[] }) =>
    call<RtMailbox>(a, `/mail/mailboxes/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(change) }),
  removeMailbox: (a: AccountInfo, id: string) =>
    call<RtMailbox>(a, `/mail/mailboxes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** POST /mail/triage: reads Inbox previews (Mail.Read) and changes nothing in the mailbox. */
  mailTriage: (a: AccountInfo, body: { since_days?: number; max_threads?: number } = {}) =>
    call<RtTriage>(a, "/mail/triage", { method: "POST", body: JSON.stringify(body) }, mailScopesFor(accountKind(a))),
  /** POST /mail/draft-reply: saves an Outlook draft, never sends. Asks for Mail.ReadWrite only now. */
  draftReply: (a: AccountInfo, messageId: string, body: string) =>
    call<RtDraftReply>(a, "/mail/draft-reply", { method: "POST", body: JSON.stringify({ message_id: messageId, body }) },
      mailDraftScopesFor(accountKind(a))),
  /** GET /close: the month that ended last (and closed months changed since), for the Home card. Reads only. */
  closeOverview: (a: AccountInfo, today: string) => call<RtCloseOverview>(a, `/close?today=${today}`),
  /** GET /close/{yyyy-mm}: status, the last run, close records, changes since the close. Reads only. */
  closeMonth: (a: AccountInfo, month: string, today: string) => call<RtCloseMonth>(a, `/close/${month}?today=${today}`),
  /** GET /audit: the audit trail, newest first (`from`, `to`, `actor`, `kind`, `limit`). Reads only. */
  audit: (a: AccountInfo, query: string) => call<RtAuditPage>(a, `/audit${query ? `?${query}` : ""}`),
  /** To-dos in _System/Todos/todos.json. */
  todos: (a: AccountInfo) => call<RtTodo[]>(a, "/todos"),
  addTodo: (a: AccountInfo, todo: RtTodoIn) => call<RtTodo>(a, "/todos", { method: "POST", body: JSON.stringify(todo) }),
  deleteTodo: (a: AccountInfo, id: string) => call<RtTodo>(a, `/todos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** POST /books/rebuild: regenerate Books.xlsx from the event files now. */
  rebuild: (a: AccountInfo) => call<RtRebuild>(a, "/books/rebuild", { method: "POST" }),
  /** POST /books/export: everything as one zip in 07 Reports/Exports; posts nothing. */
  booksExport: (a: AccountInfo) => call<RtDataExport>(a, "/books/export", { method: "POST" }),
  /** GET /books/layout: renames old-named folders (once) and lists old/new pairs left side by side. */
  layout: (a: AccountInfo) => call<RtLayout>(a, "/books/layout"),
  /** GET /books/deadlines?stagger=1 | start_month=5 | months=1 (see lib/business.ts deadlinesQuery). */
  deadlines: (a: AccountInfo, query: string) => call<RtDeadlines>(a, `/books/deadlines?${query}`),
  /** GET /books/dashboard: the Home tiles in one call (same VAT query as deadlines, plus `today`). */
  dashboard: (a: AccountInfo, query: string) => call<RtDashboard>(a, `/books/dashboard?${query}`),

  /** GET /books/vat/periods: the current VAT period and the 8 before it, by the saved VAT settings. */
  vatPeriods: (a: AccountInfo) => call<RtVatPeriods>(a, withQuery("/books/vat/periods", vatQuery())),
  /** POST /books/vat/obligations: store HMRC's obligations (fetched through the relay) so filed-elsewhere shows as submitted. */
  postVatObligations: (a: AccountInfo, obligations: RtHmrcObligation[]) =>
    call<{ stored: number }>(a, "/books/vat/obligations", { method: "POST", body: JSON.stringify({ obligations }) }),

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
  editContact: (a: AccountInfo, id: string, edits: RtContactEdits) =>
    call<RtContact>(a, `/contacts/${id}`, { method: "PUT", body: JSON.stringify(edits) }),
  importOutlookContacts: (a: AccountInfo, addNew: boolean) =>
    call<RtContactImport>(a, "/contacts/import-outlook", { method: "POST", body: JSON.stringify({ add_new: addNew }) },
      contactsScopesFor(accountKind(a))),
  statement: (a: AccountInfo, id: string, from?: string, to?: string) => {
    const q = new URLSearchParams({ ...(from ? { from } : {}), ...(to ? { to } : {}) }).toString();
    return call<RtStatement>(a, `/contacts/${id}/statement${q ? `?${q}` : ""}`);
  },
  aged: (a: AccountInfo) => call<RtAged>(a, "/contacts/aged"),
  /** POST /contacts/vat-check: HMRC Check a UK VAT number via the relay, only on the user's tap; kept on the contact. */
  vatCheck: (a: AccountInfo, body: { vrn: string; name?: string | null; contact_id?: string | null; refresh?: boolean }) =>
    call<RtVatCheckResult>(a, "/contacts/vat-check", { method: "POST", body: JSON.stringify(body) }),
  /** /lookup/* (services/runtime/app/routes_lookup.py): Companies House suggestions; nothing is saved. */
  lookupCompanies: (a: AccountInfo, q: string) =>
    call<RtCompanySearch>(a, `/lookup/companies?${new URLSearchParams({ q }).toString()}`),
  /** GET /contacts/duplicates: code evidence plus the user's model's view (ai is null when it could not answer). */
  duplicates: (a: AccountInfo) => call<RtDuplicates>(a, "/contacts/duplicates"),
  /** POST /contacts/duplicates/dismiss: remembered; never suggested again. */
  dismissDuplicates: (a: AccountInfo, ids: string[]) =>
    call<{ dismissed: string[] }>(a, "/contacts/duplicates/dismiss", { method: "POST", body: JSON.stringify({ contact_ids: ids }) }),
  /** POST /contacts/merge: the user approved, code merges. Returns the kept contact and the undo id. */
  mergeContacts: (a: AccountInfo, keep_id: string, merge_ids: string[], name?: string | null) =>
    call<RtContactMerge>(a, "/contacts/merge", { method: "POST", body: JSON.stringify({ keep_id, merge_ids, name: name ?? null }) }),
  /** POST /contacts/merge/{id}/undo: restores the exact previous entries and references. */
  undoContactMerge: (a: AccountInfo, mergeId: string) =>
    call<RtContactList>(a, `/contacts/merge/${encodeURIComponent(mergeId)}/undo`, { method: "POST" }),
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
    /** Bank rules (services/runtime/app/bank_rules.py): first match wins, in order. */
    rules: (a: AccountInfo) => call<RtBankRule[]>(a, "/books/bank/rules"),
    createRule: (a: AccountInfo, rule: RtBankRuleIn) =>
      call<RtBankRule>(a, "/books/bank/rules", { method: "POST", body: JSON.stringify(rule) }),
    updateRule: (a: AccountInfo, id: string, rule: RtBankRuleIn) =>
      call<RtBankRule>(a, `/books/bank/rules/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(rule) }),
    deleteRule: (a: AccountInfo, id: string) =>
      call<RtBankRule>(a, `/books/bank/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
    reorderRules: (a: AccountInfo, ids: string[]) =>
      call<RtBankRule[]>(a, "/books/bank/rules/reorder", { method: "POST", body: JSON.stringify({ ids }) }),
    codingOptions: (a: AccountInfo) => call<{ accounts: string[]; vat_codes: string[] }>(a, "/books/bank/coding-options"),
    /** Reconcile (services/runtime/app/bank_reconcile.py): exact and rule suggestions per open line. */
    reconcile: (a: AccountInfo) => call<RtReconcileRow[]>(a, "/books/bank/reconcile"),
    /** Ask the user's own model to code one line; null when it cannot. Labelled "suggested by AI". */
    aiSuggestion: (a: AccountInfo, lineId: string) =>
      call<RtAiSuggestion | null>(a, `/books/bank/lines/${lineId}/ai-suggestion`),
    /** Pre-fill "Create rule from this" for a line. */
    ruleDraft: (a: AccountInfo, lineId: string, from: { account?: string; vat_code?: string | null; contact?: string | null; job_id?: string | null }) => {
      const q = new URLSearchParams({
        ...(from.account ? { account: from.account } : {}),
        ...(from.vat_code ? { vat_code: from.vat_code } : {}),
        ...(from.contact ? { contact: from.contact } : {}),
        ...(from.job_id ? { job_id: from.job_id } : {}),
      }).toString();
      return call<RtBankRule>(a, `/books/bank/lines/${lineId}/rule-draft${q ? `?${q}` : ""}`);
    },
    /** Approve one suggestion: exact records the match; rule/AI posts through Review approval. */
    reconcileApprove: (a: AccountInfo, lineId: string, kind: "exact" | "refund" | "rule" | "ai", ai?: RtAiSuggestion | null) =>
      call<{ line: RtBankLine; proposal_id: string | null; event_id: string | null }>(
        a, `/books/bank/lines/${lineId}/approve`, { method: "POST", body: JSON.stringify({ kind, ai: ai ?? null }) }),
  },
  /** /personal/* (services/runtime/app/routes_personal.py). Pence in, pence out; every figure is worked out by the runtime. */
  personal: {
    categories: (a: AccountInfo) => call<RtPersonalCategory[]>(a, "/personal/categories"),
    budgets: (a: AccountInfo) => call<Record<string, number>>(a, "/personal/budgets"),
    saveBudgets: (a: AccountInfo, budgets: Record<string, number>) =>
      call<Record<string, number>>(a, "/personal/budgets", { method: "PUT", body: JSON.stringify({ budgets }) }),
    summary: (a: AccountInfo, month: string) => call<RtPersonalSummary>(a, `/personal/summary?month=${month}`),
    recurring: (a: AccountInfo) => call<RtPersonalRecurring>(a, "/personal/recurring"),
    rules: (a: AccountInfo) => call<RtPersonalRule[]>(a, "/personal/rules"),
    addRule: (a: AccountInfo, value: string, categoryId: string) =>
      call<RtPersonalRule>(a, "/personal/rules", {
        method: "POST",
        body: JSON.stringify({ match: { op: "contains", value }, category_id: categoryId }),
      }),
    deleteRule: (a: AccountInfo, id: string) => call<void>(a, `/personal/rules/${id}`, { method: "DELETE" }),
    addStarterRules: (a: AccountInfo) => call<RtPersonalRule[]>(a, "/personal/rules/starter", { method: "POST" }),
    goals: (a: AccountInfo) => call<RtGoalPlan[]>(a, "/personal/goals"),
    addGoal: (a: AccountInfo, g: RtGoalIn) => call<RtGoalPlan>(a, "/personal/goals", { method: "POST", body: JSON.stringify(g) }),
    updateGoal: (a: AccountInfo, id: string, patch: Partial<RtGoalIn>) =>
      call<RtGoalPlan>(a, `/personal/goals/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    deleteGoal: (a: AccountInfo, id: string) => call<void>(a, `/personal/goals/${id}`, { method: "DELETE" }),
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
  /** Record payment: part of the balance, all of it or more (posted Dr 1200 Bank / Cr 1100 Debtors by the runtime). */
  recordInvoicePayment: (
    a: AccountInfo,
    id: string,
    body: { amount_pence?: number; paid_on?: string; account?: "1200 Bank" | "1210 Cash"; payment_ref?: string; bank_line_id?: string | null },
  ) => call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/payments`, { method: "POST", body: JSON.stringify(body) }),
  removeInvoicePayment: (a: AccountInfo, id: string, paymentId: string) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/payments/${encodeURIComponent(paymentId)}`, { method: "DELETE" }),
  /** Posts the credit note at once: the app sends confirm only after the user ticked the confirmation. */
  createCreditNote: (
    a: AccountInfo,
    id: string,
    body: { reason: string; issue_date?: string; lines?: { line: number; quantity: string }[] | null },
  ) => call<RtCreditNote>(a, `/invoices/${encodeURIComponent(id)}/credit-notes`, { method: "POST", body: JSON.stringify({ ...body, confirm: true }) }),
  creditNotes: (a: AccountInfo, invoice?: string) =>
    call<RtCreditNote[]>(a, `/credit-notes${invoice ? `?invoice=${encodeURIComponent(invoice)}` : ""}`),
  /** A stand-alone credit note: its own customer, lines and descriptions; posted at once like one from an invoice. */
  createStandaloneCreditNote: (
    a: AccountInfo,
    body: { customer: { name: string; email?: string | null }; issue_date?: string; lines: { description: string; quantity: string; unit_price_pence: number; vat_code: string }[]; reason: string },
  ) => call<RtCreditNote>(a, "/credit-notes", { method: "POST", body: JSON.stringify({ ...body, confirm: true }) }),
  creditNotePdf: (a: AccountInfo, id: string) => call<RtCreditNotePdf>(a, `/credit-notes/${encodeURIComponent(id)}/pdf`, { method: "POST" }),
  sendCreditNote: (a: AccountInfo, id: string, email: { to: string; subject: string; body: string }) =>
    call<RtCreditNote>(a, `/credit-notes/${encodeURIComponent(id)}/send`, { method: "POST", body: JSON.stringify({ ...email, confirm: true }) },
      mailSendScopesFor(accountKind(a))),
  voidCreditNote: (a: AccountInfo, id: string, reason: string) =>
    call<RtCreditNote>(a, `/credit-notes/${encodeURIComponent(id)}/void`, { method: "POST", body: JSON.stringify({ reason }) }),
  /** POST /payments: a payment against bills (side "purchase": Dr 2100 Creditors / Cr 1200 Bank) or sales invoices. */
  recordPayment: (a: AccountInfo, body: RtPaymentIn) =>
    call<RtPaymentRecord>(a, "/payments", { method: "POST", body: JSON.stringify(body) }),
  removePayment: (a: AccountInfo, id: string) =>
    call<{ documents: string[] }>(a, `/payments/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** Post as payment: a bank line matched straight to invoices on the Bank page becomes a recorded payment. */
  paymentFromBankLine: (a: AccountInfo, lineId: string) =>
    call<RtPaymentRecord>(a, `/payments/from-bank-line/${encodeURIComponent(lineId)}`, { method: "POST" }),
  /** Credits on contacts (services/runtime/app/credits.py): apply to another document (nothing posted) or refund. */
  credits: (a: AccountInfo, side?: "sale" | "purchase") => call<RtCreditRow[]>(a, `/credits${side ? `?side=${side}` : ""}`),
  applyCredit: (a: AccountInfo, body: { credit: string; event_id: string; amount_pence?: number; date?: string }) =>
    call<RtCreditUse>(a, "/credits/apply", { method: "POST", body: JSON.stringify(body) }),
  refundCredit: (
    a: AccountInfo,
    body: { credit: string; amount_pence?: number; date?: string; account?: "1200 Bank" | "1210 Cash"; reference?: string; bank_line_id?: string },
  ) => call<RtCreditUse>(a, "/credits/refund", { method: "POST", body: JSON.stringify(body) }),
  removeCreditUse: (a: AccountInfo, id: string) =>
    call<RtCreditUse>(a, `/credits/uses/${encodeURIComponent(id)}`, { method: "DELETE" }),
  voidInvoice: (a: AccountInfo, id: string, reason: string) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/void`, { method: "POST", body: JSON.stringify({ reason }) }),
  /** Drafting sends nothing; the user reads, edits and confirms before reminderSend. */
  reminderDraft: (a: AccountInfo, id: string) =>
    call<RtReminderDraft>(a, `/invoices/${encodeURIComponent(id)}/reminder-draft`, { method: "POST" }),
  reminderSend: (a: AccountInfo, id: string, email: { to: string; subject: string; body: string }) =>
    call<RtInvoice>(a, `/invoices/${encodeURIComponent(id)}/reminder-send`, { method: "POST", body: JSON.stringify({ ...email, confirm: true }) },
      mailSendScopesFor(accountKind(a))),
  /** Online payments (services/runtime/app/routes_online_payments.py). */
  payProviders: (a: AccountInfo) => call<RtProviderStatus[]>(a, "/payments/online/providers"),
  payStart: (a: AccountInfo, provider: "stripe" | "paypal", body: { redirect_to: string; binding_hash: string }) =>
    call<{ url: string }>(a, `/payments/online/${provider}/start`, { method: "POST", body: JSON.stringify(body) }),
  payConnectStripe: (a: AccountInfo, body: { code: string; state: string; binding: string }) =>
    call<RtProviderStatus[]>(a, "/payments/online/stripe/connect", { method: "POST", body: JSON.stringify(body) }),
  payConnectPaypal: (a: AccountInfo, body: { merchant_id: string; state: string; binding: string }) =>
    call<RtProviderStatus[]>(a, "/payments/online/paypal/connect", { method: "POST", body: JSON.stringify(body) }),
  paySetPaypalMe: (a: AccountInfo, username: string) =>
    call<RtProviderStatus[]>(a, "/payments/online/paypalme", { method: "PUT", body: JSON.stringify({ username }) }),
  payDisconnect: (a: AccountInfo, provider: RtPayProvider) =>
    call<{ providers: RtProviderStatus[]; warning: string | null }>(a, `/payments/online/${provider}/disconnect`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  payCheck: (a: AccountInfo) => call<RtOnlineCheck>(a, "/payments/online/check"),
  addPaymentLink: (a: AccountInfo, id: string, provider: RtPayProvider) =>
    call<{ invoice: RtInvoice; warning: string | null }>(a, `/invoices/${encodeURIComponent(id)}/payment-link`, {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),
  removePaymentLink: (a: AccountInfo, id: string) =>
    call<{ invoice: RtInvoice; warning: string | null }>(a, `/invoices/${encodeURIComponent(id)}/payment-link`, { method: "DELETE" }),
  approveOnlinePayment: (a: AccountInfo, id: string, body: { payment_id: string; fee_pence?: number }) =>
    call<{ invoice: RtInvoice; payment: RtFoundPayment }>(a, `/invoices/${encodeURIComponent(id)}/payment-link/approve`, {
      method: "POST",
      body: JSON.stringify({ ...body, confirm: true }),
    }),
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
  /** GET /books/spending: code's figures for the period (default this month), the model's checked words. */
  spending: (a: AccountInfo, period?: { start: string; end: string } | null) =>
    call<RtSpending>(a, withQuery("/books/spending", period ? `start=${period.start}&end=${period.end}` : "")),
  /** GET /books/prices: item price history and savings from the user's own receipts (code only). */
  prices: (a: AccountInfo) => call<RtPriceReport>(a, "/books/prices"),
  /** POST /books/prices/suggest: the same, with the AI's same-product suggestions where code's rules agree. */
  suggestPrices: (a: AccountInfo) => call<RtPriceReport>(a, "/books/prices/suggest", { method: "POST" }),
  /** POST /books/prices/matches: the user's yes or no for one possible match (_System/item_matches.json). */
  decideMatch: (a: AccountInfo, body: { a: string; b: string; same: boolean }) =>
    call<{ a: string; b: string; same: boolean }>(a, "/books/prices/matches", { method: "POST", body: JSON.stringify(body) }),
  /** The shopping list in _System/shopping_list.json. */
  shopping: (a: AccountInfo) => call<RtShoppingList>(a, "/shopping"),
  shoppingLookup: (a: AccountInfo, text: string) =>
    call<RtShoppingLookup>(a, "/shopping/lookup", { method: "POST", body: JSON.stringify({ text }) }),
  addShopping: (a: AccountInfo, body: RtShoppingIn) =>
    call<RtShoppingItem>(a, "/shopping", { method: "POST", body: JSON.stringify(body) }),
  /** POST /shopping/propose: a signed Ask card from typed specs (approve with approveAction). */
  proposeShopping: (a: AccountInfo, body: RtShoppingIn) =>
    call<RtProposedAction>(a, "/shopping/propose", { method: "POST", body: JSON.stringify(body) }),
  tickShopping: (a: AccountInfo, id: string, done: boolean) =>
    call<RtShoppingItem>(a, `/shopping/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ done }) }),
  removeShopping: (a: AccountInfo, id: string) =>
    call<RtShoppingItem>(a, `/shopping/${encodeURIComponent(id)}`, { method: "DELETE" }),
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
/** POST /books/export (services/runtime/app/data_export.py): everything as one zip. */
export interface RtDataExport {
  path: string; // "07 Reports/Exports/accnomos-export-2026-10-27.zip"
  name: string;
  size: number;
  files: number; // files inside the zip
  web_url: string | null;
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
export type RtContactField =
  | "name" | "kind" | "vrn" | "email" | "phone" | "address" | "default_category" | "default_vat_code" | "vat_status"
  | "company_number";
/** PUT /contacts/{id}: the text fields, plus payment terms in days (null: the 30-day default). */
export type RtContactEdits = Partial<Record<RtContactField, string | null>> & { terms_days?: number | null };
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
  terms_days?: number | null; // payment terms in days; ageing assumes 30 when unset
  company_number?: string | null; // Companies House number (absent from runtimes before this field)
  vat_check?: RtVatCheck | null; // the last HMRC VAT check for `vrn`, kept on the contact
  aliases: string[];
  edited: string[];
  created_at: string;
  updated_at: string;
}
/** HMRC Check a UK VAT number, as the relay answers it. `source` says sandbox, live or a test-mode sample. */
export interface RtVatCheck {
  vrn: string;
  registered: boolean;
  name: string | null;
  address: string | null;
  consultation_number: string | null;
  checked_at: string;
  source: "hmrc-sandbox" | "hmrc" | "sample";
  checksum_ok?: boolean | null;
}
export interface RtVatCheckResult {
  check: RtVatCheck;
  name_differs: boolean; // HMRC's name clearly differs from the supplier's: warn, never block
  contact_id: string | null;
  cached: boolean;
}
export interface RtCompanyMatch {
  company_number: string;
  name: string;
  status: string | null;
  type: string | null;
  address: string | null;
  date_of_creation: string | null;
  source: string;
  sample: boolean;
}
export interface RtCompanySearch {
  query: string;
  items: RtCompanyMatch[];
}
export interface RtLookupStatus {
  companies_house: boolean;
  vat_check: boolean;
  sample: boolean;
}

/** GET /lookup/status: which official look-ups this runtime can do (no sign-in). Null when it can't say. */
export async function lookupStatus(): Promise<RtLookupStatus | null> {
  try {
    const res = await fetch(`${RUNTIME_URL}/lookup/status`);
    return res.ok ? ((await res.json()) as RtLookupStatus) : null;
  } catch {
    return null;
  }
}

/** "(HMRC sandbox)" / "(HMRC)" / "(sample)": where a VAT check answer came from, always shown with it. */
export function vatCheckSourceLabel(source: RtVatCheck["source"]): string {
  return source === "hmrc" ? "HMRC" : source === "hmrc-sandbox" ? "HMRC sandbox" : "SAMPLE, test mode";
}

export interface RtContactTotals {
  documents: number;
  ytd_sales_net_pence: number;
  ytd_sales_vat_pence: number;
  ytd_purchases_net_pence: number;
  ytd_purchases_vat_pence: number;
  open_receivable_pence: number; // still owed on sales invoices, after part payments and credit notes
  open_payable_pence: number;
  customer_credit_pence?: number; // the customer overpaid or was credited more than they owed: you owe it
  supplier_credit_pence?: number; // the same the other way round
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
  kind?: "invoice" | "credit_note" | "payment" | "refund" | "undo";
  payment_id?: string | null; // a payment: DELETE /payments/{id}; a refund: DELETE /credits/uses/{id}
}
/** Money left on a contact's account (an overpayment, or a credit note bigger than what was owed). */
export interface RtCredit {
  id: string; // "payment:<id>" or "credit_note:<event id>"
  side: "sale" | "purchase";
  date: string;
  amount_pence: number; // what is left after uses
  source: "payment" | "credit_note";
  source_id: string;
  doc_event_id: string; // the document it came with
}
export interface RtCreditRow extends RtCredit {
  counterparty: string;
  reference: string | null;
}
export interface RtCreditUse {
  id: string;
  kind: "apply" | "refund";
  side: "sale" | "purchase";
  date: string;
  amount_pence: number;
  applied_pence?: number; // in a statement: what it actually took
  credit: string;
  doc_event_id: string | null;
  reference: string | null;
  event_id: string | null;
  bank_line_id: string | null;
}
export interface RtOpenItem {
  event_id: string;
  side: "sale" | "purchase";
  date: string;
  due_date: string;
  reference: string | null;
  gross_pence: number;
  outstanding_pence: number;
}
export interface RtPaymentIn {
  side: "sale" | "purchase";
  date?: string;
  amount_pence?: number;
  account?: "1200 Bank" | "1210 Cash";
  reference?: string;
  allocations: { event_id: string; amount_pence: number }[];
  bank_line_id?: string;
}
export interface RtPaymentRecord {
  id: string;
  side: "sale" | "purchase";
  date: string;
  amount_pence: number;
  account: string;
  event_id: string | null;
  bank_line_id: string | null;
}
export interface RtStatement {
  contact: RtContact;
  start: string | null;
  end: string | null;
  opening_balance_pence: number;
  closing_balance_pence: number;
  credit_pence?: number; // money on the contact's account (overpaid, or credited more than owed)
  lines: RtStatementLine[];
  credits?: RtCredit[]; // that money, credit by credit
  open_documents?: RtOpenItem[]; // invoices and bills still waiting for money
  credit_uses?: RtCreditUse[]; // credits applied or refunded
}
/** "current": not due yet; the others are days past the due date (the invoice's, else terms, else 30 days). */
export type RtAgedBucket = "current" | "0-30" | "31-60" | "61-90" | "90+";
export const AGED_BUCKETS: RtAgedBucket[] = ["current", "0-30", "31-60", "61-90", "90+"];
export const agedBucketLabel = (b: RtAgedBucket) => (b === "current" ? "Not yet due" : `${b} days late`);
export interface RtAgedRow {
  contact_id: string;
  name: string;
  buckets: Record<RtAgedBucket, number>;
  total_pence: number;
  documents: {
    event_id: string;
    date: string;
    due_date?: string;
    reference: string | null;
    amount_pence: number; // still owed
    gross_pence?: number;
    age_days: number; // days past due; negative = not due yet
    bucket: RtAgedBucket;
  }[];
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
/** One possible-duplicate group (services/runtime/app/contacts.py): the model's view is advisory only. */
export interface RtDuplicateAI {
  same: boolean;
  confidence: number;
  keep_name: string;
  reason: string;
}
export interface RtDuplicateGroup {
  contact_ids: string[];
  contacts: RtContact[];
  evidence: string[];
  blocked: boolean; // different VAT numbers: code never suggests these as the same business
  ai: RtDuplicateAI | null; // null when the model could not answer; the code evidence stands alone
}
export interface RtDuplicates {
  groups: RtDuplicateGroup[];
}
export interface RtContactMerge {
  contact: RtContact;
  merge_id: string; // POST /contacts/merge/{merge_id}/undo takes the merge back
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

/** Load sample books (services/runtime/app/sample_books.py): progress kept in the user's _System/sample_seed.json. */
export interface RtSampleStatus {
  state: "none" | "running" | "needs_token" | "done" | "failed";
  /** The step being done, or the one it stopped at. */
  step: string | null;
  done: number;
  total: number;
  steps: string[];
  started_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
  /** A plain sentence when it stopped. */
  error: string | null;
  business: string | null;
  /** State "none" only: whether sample books could go into this folder (no entries, proposals or contacts). */
  empty: boolean | null;
}

/** A refused POST /books/sample: `detail` is the runtime's sentence (409: the folder already has books). */
export class SampleRefused extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** GET /books/sample. */
export function sampleStatus(account: AccountInfo): Promise<RtSampleStatus> {
  return call<RtSampleStatus>(account, "/books/sample");
}

/**
 * POST /books/sample (start, or carry on after a stop) or /books/sample/continue (while it runs: hands the runtime
 * this request's fresh Graph token, which the long background job needs once the first one expires).
 */
export async function postSample(account: AccountInfo, carryOn = false): Promise<RtSampleStatus> {
  const path = withQuery(carryOn ? "/books/sample/continue" : "/books/sample", vatQuery());
  const res = await fetch(`${RUNTIME_URL}${path}`, { method: "POST", headers: await runtimeHeaders(account) });
  if (res.ok) return (await res.json()) as RtSampleStatus;
  let detail: unknown;
  try {
    detail = ((await res.json()) as { detail?: unknown }).detail;
  } catch {
    /* not JSON */
  }
  throw new SampleRefused(
    typeof detail === "string" && detail ? detail : `Couldn't load sample books (status ${res.status}).`,
    res.status,
  );
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
  paid_pence?: number | null;
  credited_pence?: number;
  balance_pence?: number | null;
  payment_status?: RtPaymentStatus | null;
  money?: RtInvoiceMoney | null; // payments and credit notes, worked out by the runtime; null for drafts and void
  voided_at: string | null;
  void_reason: string | null;
  reminders: { sent_at: string; to: string; subject: string }[];
  days_overdue: number | null; // only while sent and unpaid; 0 or less = not due yet
  job_id: string | null;
  timesheets_marked: boolean;
  payment_link?: RtPaymentLink | null; // "Pay online" (services/runtime/app/online_payments.py)
  online_payments?: string[]; // provider payment ids already in the books
}
/** Online payments: the user's own Stripe / PayPal account (services/runtime/app/online_payments.py). */
export type RtPayProvider = "stripe" | "paypal" | "paypalme";
export interface RtPaymentLink {
  provider: RtPayProvider;
  url: string;
  amount_pence: number;
  currency: "GBP";
  test_mode: boolean;
  provider_ref: string | null;
  account_ref: string | null;
  ref: string;
  created_at: string;
  created_by: string;
}
export interface RtProviderStatus {
  provider: RtPayProvider;
  label: string;
  available: boolean; // this server can do it
  reason: string | null; // why not
  test_mode: boolean;
  connected: boolean;
  account: string | null;
  connected_at: string | null;
  can_match: boolean; // payments through it are found by code (not PayPal.me)
}
export interface RtFoundPayment {
  invoice: string;
  customer: string;
  provider: RtPayProvider;
  payment_id: string;
  date: string;
  gross_pence: number;
  fee_pence: number | null; // null: the provider has not said yet
  net_pence: number | null;
  balance_pence: number;
  test_mode: boolean;
  journal: { account: string; debit_pence: number; credit_pence: number; vat_code: string | null }[];
}
export interface RtOnlineCheck {
  checked: number;
  found: RtFoundPayment[];
  problems: { invoice: string; provider: RtPayProvider; message: string }[];
}
export type RtPaymentStatus = "open" | "part_paid" | "paid" | "overpaid";
export interface RtInvoicePayment {
  id: string; // remove it with DELETE /invoices/{number}/payments/{id}
  source: "recorded" | "bank_line" | "marked" | "credit"; // "credit": another invoice's overpayment applied here
  date: string | null;
  amount_pence: number; // the whole payment
  applied_pence: number; // the part that paid this invoice
  account: string | null;
  reference: string | null;
  description: string;
}
export interface RtInvoiceMoney {
  paid_pence: number;
  credited_pence: number;
  balance_pence: number;
  overpaid_pence: number;
  payment_status: RtPaymentStatus;
  payments: RtInvoicePayment[];
  credit_notes: { number: string | null; event_id: string; applied_pence: number; use_id?: string | null }[];
}
export interface RtCreditNote {
  number: string;
  invoice: string | null; // null: a stand-alone credit note, against no invoice
  status: "issued" | "void";
  customer: RtInvoiceCustomer;
  issue_date: string;
  lines: RtInvoiceLine[];
  source_lines: number[];
  net_pence: number;
  vat_pence: number;
  total_pence: number;
  reason: string;
  event_id: string | null;
  sent_at: string | null;
  sent_to: string | null;
  voided_at: string | null;
  void_reason: string | null;
}
export interface RtCreditNotePdf {
  path: string;
  size: number;
  sha256: string;
  data_url: string;
  email: { to: string | null; subject: string; body: string };
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
  // label: set when the entry is a recorded payment or refund ("Recorded payment of £405.00 on 20/09/2026 (…)")
  events: { id: string; date: string; counterparty: string | null; amount_pence: number; label?: string | null }[];
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
/** A bank rule (services/runtime/app/bank_rules.py): "when the description contains X, code it to Y". */
export interface RtBankRule {
  id: string;
  name: string;
  match: { op: "contains" | "equals" | "regex"; value: string };
  amount_min_pence: number | null;
  amount_max_pence: number | null;
  direction: "in" | "out" | "either";
  action: { account: string; vat_code: string | null; contact: string | null; job_id: string | null };
  created_at: string;
  created_by: string | null;
}
export interface RtBankRuleIn {
  name: string;
  match: { op: "contains" | "equals" | "regex"; value: string };
  amount_min_pence: number | null;
  amount_max_pence: number | null;
  direction: "in" | "out" | "either";
  action: { account: string; vat_code: string | null; contact: string | null; job_id: string | null };
}
/** One reconcile row (services/runtime/app/bank_reconcile.py): exact, rule and AI suggestions per open line. */
export interface RtExactSuggestion {
  kind: "exact";
  event_ids: string[];
  reference: string | null;
  reasons: string[];
}
export interface RtRuleSuggestion {
  kind: "rule";
  rule_id: string;
  rule_name: string;
  account: string;
  vat_code: string | null;
  contact: string | null;
  job_id: string | null;
  reasons: string[];
}
export interface RtAiSuggestion {
  kind: "ai";
  account: string;
  vat_code: string | null;
  contact: string | null;
  reason: string;
  by: string; // always "suggested by AI"
}
/** A contact's credit of the line's amount that the line pays back (approve: records the refund and matches). */
export interface RtRefundSuggestion {
  kind: "refund";
  credit: string;
  side: "sale" | "purchase";
  counterparty: string;
  amount_pence: number;
  reasons: string[];
}
export interface RtReconcileRow {
  line_id: string;
  exact: RtExactSuggestion | null;
  refund?: RtRefundSuggestion | null;
  rule: RtRuleSuggestion | null;
  ai: RtAiSuggestion | null;
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
  /** True when no stagger was sent (none saved in Settings), so calendar quarters (stagger 1) were assumed. */
  assumed?: boolean;
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
/** A tile the runtime could not read just now (a storage or Graph failure on that read); the rest still load. */
export interface RtTileError {
  error: string;
}
export function isTileError(x: unknown): x is RtTileError {
  return typeof x === "object" && x !== null && "error" in x && typeof (x as RtTileError).error === "string";
}
/** The tile's data, or null when it is missing or came back as an error. */
export function tileData<T>(x: T | RtTileError | null | undefined): T | null {
  return x === null || x === undefined || isTileError(x) ? null : x;
}
export interface RtDashboard {
  today: string;
  cash: ({
    balance_pence: number | null; // closing balance on the latest statement with a matched line
    as_of: string | null;
    bank: string | null;
    statement: string | null;
    reconciled_to: string | null;
  } | RtTileError) | null;
  owed_to_you: (RtOwed & { overdue: number | null; overdue_pence: number | null; most_overdue_days: number | null }) | RtTileError | null;
  owed_by_you: RtOwed | RtTileError | null;
  vat: RtDeadlines | RtTileError | null;
  attention: ({
    proposed: number;
    needs_a_look: number;
    unmatched_bank_lines: number;
    overdue_invoices: number | null;
    total: number;
  } | RtTileError) | null;
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
  kind: "open_review" | "open_vat" | "chase_supplier" | "plan_day" | "open_spending" | "none"; // plan_day: arg = YYYY-MM-DD
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
  served_by?: RtServedBy | null; // the provider that wrote the words (none when code did)
  proposed_action?: RtProposedAction | null; // an instruction: show the card; nothing happens until Approve
  clarification?: RtClarification | null; // an instruction Ask needs one more detail for
}
/** Proposed actions (services/runtime/app/actions.py). Kept by the app only; post back unchanged to approve. */
export type RtActionKind =
  | "create_invoice"
  | "chase_invoice"
  | "log_mileage"
  | "log_timesheet"
  | "match_bank_line" // proposed by the month-end close
  | "close_month" // proposed by the month-end close
  | "add_to_shopping_list";
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
/** match_bank_line: a match code suggested during the month-end close; approving records it (posts nothing). */
export interface RtBankMatchPreview {
  month: string;
  line_id: string;
  date: string;
  amount_pence: number;
  description: string;
  bank: string;
  event_ids: string[];
  to: string;
  reasons: string[];
  warnings: string[];
}
/** close_month: approving records the close with this snapshot; refused if the month's figures changed since. */
export interface RtCloseMonthPreview {
  month: string;
  label: string;
  snapshot_hash: string;
  reclose: boolean;
  figures: { sales_pence: number; cost_of_sales_pence: number; overheads_pence: number; net_profit_pence: number };
  entries: number;
  bank_lines: number;
  changes: string[];
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
  /** add_to_shopping_list with nothing in the history: ask for these as fields, then POST /shopping/propose. */
  spec_fields?: (RtSpecField & { value?: string })[];
  /** What code already resolved, sent back with the specs (the shopping item's job). */
  extra?: { job_id?: string | null; job_name?: string | null };
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
  items: { name: string; subject: string; from_address: string; score: number; mailbox?: string }[];
  mailbox_id?: string;
  mailbox?: string; // the address read
  filtered_senders?: number;
}

/** A mailbox Outlook intake reads (services/runtime/app/mailboxes.py). */
export type RtMailboxKind = "primary" | "microsoft" | "shared";
export interface RtMailbox {
  id: string; // "primary" for the signed-in account's own
  address: string;
  kind: RtMailboxKind;
  folder: string; // "all", "inbox", "archive" or a top-level folder's name
  allow_senders: string[];
  deny_senders: string[];
  added_at?: string | null;
  last_scan_at?: string | null;
  last_scan_saved?: number | null;
  last_scan_error?: string | null;
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
/** One audit line, as services/runtime/app/audit_view.py AuditEntry. */
export interface RtAuditEntry {
  ts: string;
  actor: string; // "user:<email>" or "agent:<name>"
  actor_kind: "user" | "agent" | "accountant";
  actor_label: string; // "You", "Autopilot", "Intake", "Triage", "Planner", ...
  event: string; // e.g. "approved"; Ask actions are action_done / action_rejected / action_failed
  summary: string;
  refs: { proposal: string | null; event: string | null; invoice: string | null; action: string | null; file: string | null };
}
export interface RtAuditPage {
  start: string;
  end: string;
  entries: RtAuditEntry[]; // newest first
  truncated: boolean;
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
  submitted: boolean; // HMRC says fulfilled, or a relay submission receipt is saved in 06 VAT returns
  submitted_source?: "hmrc" | "accnomos" | null; // who says it is submitted
  received?: string | null; // when HMRC received the return (ISO date), when it says fulfilled
  can_submit: boolean; // current or previous period and not yet submitted
  boxes: RtVatBox[];
  event_ids: string[];
  warnings: string[];
  events_in_period: number;
  undone_in_period: number; // reversing events among them
  hmrc_body: Record<string, unknown>;
}

/** POST /books/vat/obligations (services/runtime/app/routes_vat.py): one HMRC obligation, as the relay returns it. */
export interface RtHmrcObligation {
  periodKey: string;
  start: string;
  end: string;
  due: string;
  status: "O" | "F";
  received?: string;
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
  submitted_source?: "hmrc" | "accnomos" | null; // who says it is submitted
  received?: string | null; // when HMRC received the return (ISO date), when it says fulfilled
  entries: number;
  can_submit: boolean;
}
export interface RtVatPeriods {
  today: string;
  months: number;
  start_month: number;
  periods: RtVatPeriod[]; // current first, then the 8 before it
  warnings: string[]; // e.g. our periods do not match the ones HMRC holds
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

/** Personal finances (services/runtime/app/personal.py). Money in whole pence. */
export interface RtPersonalCategory {
  id: string;
  name: string;
}
export interface RtCategorySpend {
  id: string;
  name: string;
  spent_pence: number;
  budget_pence: number | null;
  remaining_pence: number | null;
  percent: number | null;
  state: "none" | "ok" | "near" | "over";
}
export interface RtPersonalSummary {
  month: string;
  lines: number;
  income_pence: number;
  spent_pence: number;
  left_pence: number;
  budget_total_pence: number;
  categories: RtCategorySpend[];
  uncategorised_count: number;
  uncategorised_pence: number;
  notes: string[];
}
export interface RtRecurringItem {
  key: string;
  label: string;
  category_name: string;
  cadence: "weekly" | "fortnightly" | "monthly" | "quarterly" | "annually";
  amount_pence: number;
  amount_varies: boolean;
  occurrences: number;
  last_date: string;
  next_due: string;
  days_until: number;
  status: "upcoming" | "overdue" | "stopped";
  monthly_equivalent_pence: number;
}
export interface RtPersonalRecurring {
  items: RtRecurringItem[];
  monthly_total_pence: number;
  note: string;
}
export interface RtPersonalRule {
  id: string;
  name: string;
  match: { op: "contains" | "equals" | "regex"; value: string };
  category_id: string;
}
export interface RtGoalIn {
  name: string;
  target_pence: number;
  target_date: string;
  saved_pence?: number;
  planned_monthly_pence?: number | null;
}
export interface RtGoalPlan {
  goal: RtGoalIn & { id: string; saved_pence: number };
  remaining_pence: number;
  percent: number;
  months_left: number;
  monthly_needed_pence: number;
  status: "reached" | "on_track" | "behind" | "plan_needed" | "date_passed";
  projected_date: string | null;
  estimate: boolean;
}

export const gbp = (n: number) => `£${n.toFixed(2)}`;
export const ukDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

// --------------------------------------------------------------------------- //
// Files page: overview, index, moves, archive by year, backups
// (services/runtime/app/routes_files.py, app/files.py, app/archive.py, app/backups.py)
// --------------------------------------------------------------------------- //

export type RtFileKind = "pdf" | "image" | "spreadsheet" | "csv" | "json" | "text" | "zip" | "other";

export interface RtFileLink {
  proposal_id: string | null;
  event_id: string | null;
  amount_pence: number | null; // the ledger entry's net + VAT
  counterparty: string | null;
  doc_date: string | null;
  bank_lines: number;
}

export interface RtIndexedFile {
  path: string;
  name: string;
  folder: string;
  kind: RtFileKind;
  size: number;
  modified: string | null;
  date: string;
  date_from: "document" | "name" | "folder" | "modified" | "today";
  tax_year: string;
  archived: boolean;
  protected: boolean; // the app will not move, rename or trash it
  web_url: string | null;
  linked: RtFileLink | null;
}

export interface RtFileIndex {
  files: RtIndexedFile[];
  folders: string[]; // folders a document can be moved to
  truncated: boolean;
}

export interface RtDuplicateFile {
  path: string;
  size: number;
  modified: string | null;
  web_url: string | null;
  keep: boolean;
  linked: boolean;
  protected: boolean;
}

export interface RtStorageOverview {
  total_files: number;
  total_bytes: number;
  folders: { folder: string; files: number; bytes: number }[];
  years: { year: string; files: number; bytes: number; archived_files: number }[];
  largest: RtIndexedFile[];
  duplicates: { hash: string; size: number; files: RtDuplicateFile[] }[];
  duplicate_bytes: number;
  truncated: boolean;
}

export interface RtMoved {
  old: string;
  new: string;
}

export type RtYearKind = "tax" | "financial";

export interface RtArchiveRequest {
  up_to?: string | null;
  kind: RtYearKind;
  end_month?: number;
  end_day?: number;
  zip?: boolean;
}

export interface RtArchiveYear {
  label: string;
  start: string;
  end: string;
  files: number;
  bytes: number;
  current: boolean;
}

export interface RtArchiveMove {
  old: string;
  new: string;
  year: string;
  size: number;
}

export interface RtArchivePreview {
  kind: RtYearKind;
  up_to: string | null;
  years: RtArchiveYear[];
  moves: RtArchiveMove[];
  bytes: number;
}

export interface RtArchiveRun {
  id: string;
  created_at: string;
  by: string;
  kind: RtYearKind;
  up_to: string;
  moves: RtArchiveMove[];
  zips: { year: string; path: string | null; files: number; note: string | null }[];
  undone_at: string | null;
  undone_by: string | null;
  undo_skipped: string[];
}

export interface RtBackup {
  path: string;
  name: string;
  day: string;
  size: number;
  files: number | null;
  sha256: string | null;
  web_url: string | null;
  has_checksum: boolean;
}

export interface RtFileSettings {
  backup_keep: number;
  monthly_backup: boolean;
}

export interface RtBackupVerification {
  path: string;
  ok: boolean;
  checksum: "ok" | "mismatch" | "missing";
  files: number;
  problems: string[];
}

export interface RtRestorePreview {
  path: string;
  verification: RtBackupVerification;
  books_empty: boolean;
  needs_confirmation: boolean;
  confirm_word: string;
  counts: { new: number; same: number; changed: number; kept: number };
  items: { path: string; status: "new" | "same" | "changed" | "kept"; size: number }[];
  note: string;
}

export interface RtRestoreResult {
  path: string;
  restored: number;
  replaced: number;
  kept: number;
  trash: string | null;
}

const post = (body?: unknown): RequestInit => ({ method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const filesApi = {
  overview: (a: AccountInfo) => call<RtStorageOverview>(a, "/files/overview"),
  index: (a: AccountInfo) => call<RtFileIndex>(a, "/files/index"),
  move: (a: AccountInfo, paths: string[], to: string) => call<{ moved: RtMoved[] }>(a, "/files/move", post({ paths, to })),
  rename: (a: AccountInfo, path: string, name: string) => call<RtMoved>(a, "/files/rename", post({ path, name })),
  trash: (a: AccountInfo, paths: string[]) => call<{ moved: RtMoved[] }>(a, "/files/trash", post({ paths })),
  archivePreview: (a: AccountInfo, req: RtArchiveRequest) => call<RtArchivePreview>(a, "/files/archive/preview", post(req)),
  archive: (a: AccountInfo, req: RtArchiveRequest) => call<RtArchiveRun>(a, "/files/archive", post(req)),
  archiveRuns: (a: AccountInfo) => call<RtArchiveRun[]>(a, "/files/archive/runs"),
  undoArchive: (a: AccountInfo, id: string) => call<RtArchiveRun>(a, `/files/archive/runs/${encodeURIComponent(id)}/undo`, post()),
  backups: (a: AccountInfo) => call<{ backups: RtBackup[]; settings: RtFileSettings }>(a, "/backups"),
  backUp: (a: AccountInfo) => call<{ backup: RtBackup; retired: string[] }>(a, "/backups", post()),
  autoBackup: (a: AccountInfo) => call<{ ran: boolean }>(a, "/backups/auto", post()),
  saveBackupSettings: (a: AccountInfo, s: RtFileSettings) =>
    call<RtFileSettings>(a, "/backups/settings", { method: "PUT", body: JSON.stringify(s) }),
  verifyBackup: (a: AccountInfo, path: string) => call<RtBackupVerification>(a, "/backups/verify", post({ path })),
  restorePreview: (a: AccountInfo, path: string) => call<RtRestorePreview>(a, "/backups/restore/preview", post({ path })),
  restore: (a: AccountInfo, path: string, confirm: string | null) =>
    call<RtRestoreResult>(a, "/backups/restore", post({ path, confirm })),
};

/** This device runs the monthly backup check (components/files/MonthlyBackup.tsx) only while this is "1". */
export const MONTHLY_BACKUP_KEY = "accnomos.monthlyBackup";
export const BACKUP_CHECKED_KEY = "accnomos.backupChecked"; // "YYYY-MM" of the last check on this device

/** The month-end close (services/runtime/app/month_end.py). Money in pence; texts are written by code. */
export type RtCloseStepId = "inbox" | "bank" | "sales" | "purchases" | "payroll" | "vat" | "checks" | "reports" | "lock";
export interface RtCloseFinding {
  text: string;
  level: "blocking" | "needs_you" | "note";
  link: string | null;
  refs: Record<string, unknown>;
}
export interface RtCloseStep {
  id: RtCloseStepId;
  n: number;
  title: string;
  status: "ok" | "needs_you" | "blocked";
  reason: string;
  link: string | null;
  checked: string[];
  found: RtCloseFinding[];
  proposes: string[];
  data: Record<string, unknown>;
  ms: number;
}
export interface RtCloseFigureChange {
  label: string;
  before: string;
  after: string;
}
export interface RtCloseChanges {
  closed_at: string;
  closed_by: string;
  count: number;
  items: string[];
  figures: RtCloseFigureChange[];
  vat_note: string | null;
  headline: string;
}
export interface RtCloseStoredRun {
  id: string;
  month: string;
  label: string;
  started_at: string;
  finished_at: string;
  by: string;
  steps: RtCloseStep[];
  cards: { id: string; kind: string; summary_md: string }[];
  summary_md: string;
  summary_model: string;
  summary_fallback_reason: string | null;
  needs_you: number;
  blocking: number;
  can_close: boolean;
  snapshot_hash: string;
}
export interface RtCloseRun extends RtCloseStoredRun {
  actions: RtProposedAction[];
  changes: RtCloseChanges | null;
}
export interface RtCloseStatus {
  month: string;
  label: string;
  ended: boolean;
  closed: boolean;
  closed_at: string | null;
  closed_by: string | null;
  last_run_at: string | null;
  needs_you: number | null;
  blocking: number | null;
  can_close: boolean | null;
  changes: RtCloseChanges | null;
  headline: string;
}
export interface RtCloseRecord {
  id: string;
  month: string;
  closed_at: string;
  closed_by: string;
  snapshot_hash: string;
  report_path: string | null;
  reclose: boolean;
  changes_since_previous: string[];
}
export interface RtCloseMonth extends RtCloseStatus {
  run: RtCloseStoredRun | null;
  closes: RtCloseRecord[];
}
export interface RtCloseOverview {
  today: string;
  target: RtCloseStatus;
  changed: RtCloseStatus[];
}
export interface RtCloseStart {
  run_id: string;
  month: string;
  label: string;
  steps: { id: RtCloseStepId; n: number; title: string }[];
}
export interface RtCloseSummary {
  summary_md: string;
  model: string;
  fallback_reason: string | null;
}

/**
 * POST /close/{month}/run?stream=1 (server-sent events): `onStart` gets the nine steps, `onStep` each one as the
 * runtime finishes it, `onSummary` the checked summary; resolves to the whole run with its signed cards. With
 * `outlook` the token also asks for Mail.Read and the runtime reads the mailbox in a dry run (nothing copied).
 */
export async function closeRunStream(
  account: AccountInfo,
  month: string,
  today: string,
  outlook: boolean,
  on: { onStart?: (s: RtCloseStart) => void; onStep?: (s: RtCloseStep) => void; onSummary?: (s: RtCloseSummary) => void },
): Promise<RtCloseRun> {
  const query = [vatQuery(), `today=${today}`, "stream=1"].filter(Boolean).join("&");
  const extra = outlook ? mailScopesFor(accountKind(account)) : [];
  const headers = { ...(await runtimeHeaders(account, extra)), "Content-Type": "application/json", Accept: "text/event-stream" };
  const path = `/close/${month}/run?${query}`;
  const res = await fetch(`${RUNTIME_URL}${path}`, { method: "POST", headers, body: JSON.stringify({ outlook }) });
  if (!res.ok) throw new Error(await errorDetail(res, `POST ${path}`));
  if (!res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) throw new Error("No event stream");
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) throw new Error("The close stopped before it finished; run it again.");
    buffer += value;
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload: unknown = JSON.parse(data);
      if (event === "start") on.onStart?.(payload as RtCloseStart);
      else if (event === "step") on.onStep?.(payload as RtCloseStep);
      else if (event === "summary") on.onSummary?.(payload as RtCloseSummary);
      else if (event === "error") throw new Error((payload as { detail: string }).detail);
      else if (event === "run") {
        void reader.cancel();
        return payload as RtCloseRun;
      }
    }
  }
}

/** Spending, cheaper options and the shopping list (services/runtime/app/spending.py, prices.py, shopping.py). */
export interface RtSpendRow {
  name: string;
  net: string; // pounds before VAT
  count: number;
  change_vs_previous: string;
  change_pct: string | null;
}
export interface RtSpendingFacts {
  this_period: {
    label: string;
    start: string;
    end: string;
    spent: string;
    vat: string;
    purchases: number;
    by_category: RtSpendRow[];
    by_supplier: RtSpendRow[];
    top_items: { item: string; net: string; quantity: string; suppliers: string[] }[];
    with_line_items: number;
  };
  previous_period: { label: string; start: string; end: string; spent: string; purchases: number };
  change: { spent_vs_previous: string; spent_change_pct: string | null };
  recurring: { supplier: string; kind: "subscription" | "utility" | "regular"; category: string; months_seen: number; usual_month: string; this_period: string }[];
  unusual: { date: string; supplier: string; category: string; net: string; times_usual_purchase: string; why: string; source: string }[];
  sources: string[];
}
export interface RtSpending {
  period: { start: string; end: string };
  previous: { start: string; end: string };
  facts: RtSpendingFacts;
  summary_md: string;
  summary_by: "model" | "code";
  fallback_reason: string | null;
  model: string;
}
export interface RtPaid {
  supplier: string;
  description: string;
  date: string;
  unit_price: string;
  per_measure: string;
  pack: number;
  source: string;
}
export interface RtSaving {
  per_month: string;
  per_year: string;
  monthly_volume: string;
  monthly_items: string;
  explanation: string;
}
export interface RtLiveOffer {
  source: string;
  retrieved_at: string;
  supplier: string;
  title: string;
  url: string;
  unit_price: string;
  pack: number;
  per_measure: string | null;
  measure_word: string;
  comparable: boolean;
  note: string;
}
export interface RtPriceGroup {
  id: string;
  name: string;
  measure: "m" | "kg" | "l" | "item";
  measure_word: string;
  keys: string[];
  match: "same" | "equivalent";
  joined_by: string[];
  observations: number;
  suppliers: string[];
  latest: RtPaid;
  cheapest: RtPaid;
  by_supplier: RtPaid[];
  saving: RtSaving | null;
  monthly_volume: string;
  average_paid: string;
  live_offers: RtLiveOffer[];
  live_saving: RtSaving | null;
}
export interface RtSearchStatus {
  enabled: boolean;
  provider: string | null;
  note: string;
}
export interface RtPriceReport {
  since: string;
  until: string;
  lines_read: number;
  groups: RtPriceGroup[];
  possible_matches: { a: string; b: string; a_name: string; b_name: string; rules_ok: boolean; rules_note: string; ai_says_same: boolean | null }[];
  total_saving_per_year: string;
  coverage_note: string;
  web_search: RtSearchStatus;
  ai_used: boolean;
  ai_note: string | null;
}
export interface RtSpecField {
  name: "width_mm" | "length_m" | "colour" | "quantity";
  label: string;
  kind: "number" | "choice";
  unit: string | null;
  options: string[];
  required: boolean;
}
export interface RtSuggested {
  supplier: string;
  description: string;
  unit_price: string;
  per_measure: string;
  measure_word: string;
  date: string;
  source: string;
  basis: string;
}
export interface RtShoppingItem {
  id: string;
  text: string;
  description: string;
  quantity: string;
  spec: Record<string, string | number | null>;
  item_key: string | null;
  suggested: RtSuggested | null;
  live_offer: RtLiveOffer | null;
  note: string;
  job_id: string | null;
  job_name: string | null;
  added_at: string;
  added_by: string;
  done: boolean;
  done_at: string | null;
}
export interface RtShoppingList {
  items: RtShoppingItem[];
  web_search: RtSearchStatus;
  future_steps: Record<string, string>;
}
export interface RtLookupOption {
  key: string;
  description: string;
  supplier: string;
  unit_price: string;
  per_measure: string;
  measure_word: string;
  date: string;
  source: string;
  cheapest: RtSuggested | null;
  label: string;
}
export interface RtShoppingLookup {
  text: string;
  read_as: Record<string, string | number | null>;
  options: RtLookupOption[];
  fields: RtSpecField[];
  question_md: string;
  live_offers: RtLiveOffer[];
  web_search: RtSearchStatus;
}
export interface RtShoppingIn {
  text: string;
  option_key?: string | null;
  spec?: { width_mm?: string | null; length_m?: string | null; colour?: string | null } | null;
  quantity?: string;
  note?: string;
  job_id?: string | null;
}
export interface RtShoppingPreview {
  text: string;
  description: string;
  quantity: string;
  suggested: RtSuggested | null;
  live_offer: RtLiveOffer | null;
  job_name: string | null;
  warnings: string[];
}

/**
 * Accountant collaboration (services/runtime/app/routes_accountant.py). Settings › Your accountant and the portal
 * always use your own books (`own`), even while a client is open in this tab; queries follow the open client.
 */
const own = { own: true };
export const accountantApi = {
  settings: (a: AccountInfo) => call<RtAccountantSettings>(a, "/accountant", {}, [], own),
  saveProfile: (a: AccountInfo, profile: RtClientProfile) =>
    call<RtClientProfile>(a, "/accountant/profile", { method: "PUT", body: JSON.stringify(profile) }, [], own),
  invite: (a: AccountInfo, body: { email: string; name: string; role: "read" | "edit"; method: "graph" | "manual"; message: string }) =>
    call<RtInvitation>(
      a, "/accountant/invitations", { method: "POST", body: JSON.stringify(body) },
      body.method === "graph" && isPersonalAccount(a) ? SHARE_SCOPES : [], own,
    ),
  revoke: (a: AccountInfo, id: string) =>
    call<RtInvitation>(a, `/accountant/invitations/${encodeURIComponent(id)}/revoke`, { method: "POST" },
      isPersonalAccount(a) ? SHARE_SCOPES : [], own),
  teamOptIn: (a: AccountInfo, body: { agree: boolean; consent_version: string; role: "read" | "edit" }) =>
    call<RtInvitation>(a, "/accountant/team", { method: "POST", body: JSON.stringify(body) },
      isPersonalAccount(a) ? SHARE_SCOPES : [], own),
  teamOptOut: (a: AccountInfo) =>
    call<RtInvitation>(a, "/accountant/team", { method: "DELETE" }, isPersonalAccount(a) ? SHARE_SCOPES : [], own),
  portal: (a: AccountInfo) => call<RtPortal>(a, "/accountant/portal", {}, PORTAL_SCOPES, own),
  addClient: (a: AccountInfo, code: string) =>
    call<{ drive_id: string; item_id: string; name: string }>(
      a, "/accountant/portal/clients", { method: "POST", body: JSON.stringify({ code }) }, PORTAL_SCOPES, own,
    ),
  removeClient: (a: AccountInfo, code: string) =>
    call<{ removed: boolean }>(a, `/accountant/portal/clients/${encodeURIComponent(code)}`, { method: "DELETE" }, PORTAL_SCOPES, own),
  queries: (a: AccountInfo, q: { status?: "open" | "resolved"; waiting_on?: "client" | "accountant" } = {}, mine = false) =>
    call<RtQuery[]>(a, withQuery("/queries", new URLSearchParams(q as Record<string, string>).toString()), {}, [], { own: mine }),
  openQuery: (a: AccountInfo, body: { subject: { kind: QuerySubjectKind; ref: string; label: string }; text: string }, mine = false) =>
    call<RtQuery>(a, "/queries", { method: "POST", body: JSON.stringify(body) }, [], { own: mine }),
  reply: (a: AccountInfo, id: string, text: string, mine = false) =>
    call<RtQuery>(a, `/queries/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ text }) }, [], { own: mine }),
  resolve: (a: AccountInfo, id: string, mine = false) =>
    call<RtQuery>(a, `/queries/${encodeURIComponent(id)}/resolve`, { method: "POST" }, [], { own: mine }),
};

// --------------------------------------------------------------------------- //
// /import/*: history and opening balances from another system (services/runtime/app/routes_import.py)
// --------------------------------------------------------------------------- //

export type RtImportKind = "trial_balance" | "chart_of_accounts" | "contacts" | "open_items" | "bank_balances";
export type RtImportVendor = "xero" | "quickbooks" | "sage50" | "sage_accounting" | "freeagent" | "spreadsheet";

export const IMPORT_VENDORS: { id: RtImportVendor; label: string }[] = [
  { id: "xero", label: "Xero" },
  { id: "quickbooks", label: "QuickBooks Online" },
  { id: "sage50", label: "Sage 50 Accounts" },
  { id: "sage_accounting", label: "Sage Accounting" },
  { id: "freeagent", label: "FreeAgent" },
  { id: "spreadsheet", label: "A spreadsheet" },
];

export const IMPORT_KINDS: { id: RtImportKind; label: string }[] = [
  { id: "trial_balance", label: "Trial balance" },
  { id: "chart_of_accounts", label: "Chart of accounts" },
  { id: "contacts", label: "Contacts" },
  { id: "open_items", label: "Open invoices and bills" },
  { id: "bank_balances", label: "Bank balances" },
];

export interface RtImportFile {
  id: string;
  name: string;
  kind: RtImportKind;
  vendor: RtImportVendor | null;
  rows: number;
  skipped: string[];
  uploaded_at: string;
}

export interface RtImportMappingRow {
  key: string;
  code: string | null;
  name: string;
  type: string | null;
  klass: string | null;
  balance_pence: number;
  target: string | null;
  how: "code" | "name" | "type" | "user" | null;
  new: boolean;
  suggested: string | null;
}

export interface RtImportCheck {
  id: string;
  severity: "error" | "warning" | "info";
  ok: boolean;
  message: string;
  expected_pence: number | null;
  actual_pence: number | null;
}

export interface RtImportOpenItem {
  id: string;
  side: "sale" | "purchase";
  contact: string;
  number: string | null;
  date: string;
  due_date: string | null;
  total_pence: number;
  due_pence: number;
}

export interface RtImportDraftView {
  draft: {
    vendor: RtImportVendor | null;
    conversion_date: string | null;
    pl_treatment: "keep" | "retained";
    files: RtImportFile[];
    mapping: Record<string, string>;
  };
  balance_date: string | null;
  accounts: RtImportMappingRow[];
  journal: { account: string; debit_pence: number; credit_pence: number; sources: string[] }[];
  debits_pence: number;
  credits_pence: number;
  contacts: number;
  items: RtImportOpenItem[];
  banks: { account: string; balance_pence: number; date: string | null }[];
  checks: RtImportCheck[];
  can_post: boolean;
  needs_accept: boolean;
  chart: string[];
}

export interface RtImportRecord {
  id: string;
  vendor: RtImportVendor | null;
  conversion_date: string;
  balance_date: string;
  event_id: string;
  posted_at: string;
  posted_by: string;
  items: RtImportOpenItem[];
  contacts_added: string[];
  report_path: string | null;
  undone_at: string | null;
}

export interface RtImportReconciliation {
  balance_date: string;
  rows: { account: string; sources: string[]; source_pence: number; accnomos_pence: number; ok: boolean }[];
  source_debits_pence: number;
  source_credits_pence: number;
  accnomos_debits_pence: number;
  accnomos_credits_pence: number;
  checks: RtImportCheck[];
  proved: boolean;
  undone: boolean;
}

export interface RtImportEdit {
  vendor?: RtImportVendor;
  conversion_date?: string;
  pl_treatment?: "keep" | "retained";
  mapping?: Record<string, string | null>;
}

export const importApi = {
  draft: (a: AccountInfo) => call<RtImportDraftView>(a, "/import"),
  upload: (a: AccountInfo, file: File, opts: { kind?: RtImportKind; vendor?: RtImportVendor; side?: "sale" | "purchase" }) => {
    const form = new FormData();
    form.append("file", file, file.name);
    if (opts.kind) form.append("kind", opts.kind);
    if (opts.vendor) form.append("vendor", opts.vendor);
    if (opts.side) form.append("side", opts.side);
    return call<RtImportDraftView>(a, "/import/files", { method: "POST", body: form });
  },
  removeFile: (a: AccountInfo, id: string) =>
    call<RtImportDraftView>(a, `/import/files/${encodeURIComponent(id)}`, { method: "DELETE" }),
  edit: (a: AccountInfo, body: RtImportEdit) => call<RtImportDraftView>(a, "/import", { method: "PUT", body: JSON.stringify(body) }),
  discard: (a: AccountInfo) => call<RtImportDraftView>(a, "/import", { method: "DELETE" }),
  post: (a: AccountInfo, acceptWarnings: boolean) =>
    call<RtImportRecord>(a, "/import/post", post({ accept_warnings: acceptWarnings })),
  opening: (a: AccountInfo) =>
    call<{ record: RtImportRecord | null; reconciliation: RtImportReconciliation | null }>(a, "/import/opening"),
  undo: (a: AccountInfo) => call<RtImportRecord>(a, "/import/undo", post()),
  /** The reconciliation CSV, fetched with the user's headers (a plain link could not carry the Graph token). */
  reportCsv: async (a: AccountInfo): Promise<Blob> => {
    const res = await fetch(`${RUNTIME_URL}/import/opening/report.csv`, { headers: await runtimeHeaders(a) });
    if (!res.ok) throw new Error(await errorDetail(res, "GET /import/opening/report.csv"));
    return res.blob();
  },
  template: async (a: AccountInfo, kind: RtImportKind): Promise<Blob> => {
    const res = await fetch(`${RUNTIME_URL}/import/templates/${kind}.csv`, { headers: await runtimeHeaders(a) });
    if (!res.ok) throw new Error(await errorDetail(res, `GET /import/templates/${kind}.csv`));
    return res.blob();
  },
};
