"use client";

/**
 * The runtime's support endpoints (services/runtime/app/support/routes.py): the support assistant, the PayPal help
 * panel, the user's tickets, and the admin queue. Plain runtime calls, with the same headers as everything else.
 */
import type { AccountInfo } from "@azure/msal-browser";
import { runtimeCall, type RtProposedAction } from "./runtime";
import { recentErrors } from "./recent-errors";

export type TicketStatus = "open" | "pending" | "solved";
export type TicketCategory = "how_to" | "bug" | "account" | "billing" | "paypal" | "hmrc_vat" | "bank" | "storage" | "mobile" | "other";

export const TICKET_CATEGORIES: { id: TicketCategory; label: string }[] = [
  { id: "how_to", label: "How do I…" },
  { id: "bug", label: "Something is broken" },
  { id: "account", label: "Account and sign-in" },
  { id: "billing", label: "Plan and billing" },
  { id: "paypal", label: "PayPal" },
  { id: "hmrc_vat", label: "VAT and HMRC" },
  { id: "bank", label: "Bank" },
  { id: "storage", label: "OneDrive or Google Drive" },
  { id: "mobile", label: "Android app" },
  { id: "other", label: "Something else" },
];
export const categoryLabel = (id: string) => TICKET_CATEGORIES.find((c) => c.id === id)?.label ?? id;

/** What the user sees; "pending" is the admin waiting for the user. */
export const STATUS_LABEL: Record<TicketStatus, string> = { open: "Open", pending: "Waiting for you", solved: "Solved" };
/** The same statuses as the admin queue reads them. */
export const ADMIN_STATUS_LABEL: Record<TicketStatus, string> = { open: "Open", pending: "Pending (waiting for the user)", solved: "Solved" };

export interface SupportCitation {
  id: string;
  title: string;
  path: string;
  url: string;
}
export interface AssistAnswer {
  answer_md: string;
  citations: SupportCitation[];
  ticket_card: RtProposedAction | null;
  ticket_note: string | null;
  transcript?: string | null;
}
export interface TicketMessage {
  id: string;
  at: string;
  author: "user" | "admin";
  body: string;
  internal: boolean;
  emailed: boolean;
  author_email: string | null;
}
export interface Ticket {
  id: string;
  number: number;
  subject: string;
  category: string;
  status: TicketStatus;
  source: string;
  page: string | null;
  app: string | null;
  version: string | null;
  created_at: string;
  updated_at: string;
  last_reply_by: string | null;
  solved_at: string | null;
  context: Record<string, unknown>;
  email: string | null;
  account_id: string | null;
}
export interface TicketThread extends Ticket {
  messages: TicketMessage[];
}
export interface TicketPage {
  items: Ticket[];
  page: number;
  per_page: number;
  total: number;
}
export interface AdminTicketPage extends TicketPage {
  counts: Record<TicketStatus, number>;
}
export interface AdminReply extends TicketThread {
  emailed: boolean;
  email_note: string | null;
}
export interface PayPalHelp {
  available: boolean;
  connected: boolean;
  test_mode: boolean | null;
  account: string | null;
  connected_at: string | null;
  last_synced_at: string | null;
  open_disputes: { dispute_id: string; reason: string; status: string; respond_by: string | null; invoice: string | null; sample: boolean; can_send_evidence: boolean }[];
  problem: string | null;
  links: { label: string; url: string }[];
  no_case_api: string;
}

/** The consent boxes on a ticket: only what is ticked is sent. */
export interface Consent {
  attach_errors: boolean;
  include_paypal: boolean;
  include_financial: boolean;
  conversation?: { role: "user" | "assistant"; text: string }[];
}

function consentBody(c: Consent) {
  return {
    attach_errors: c.attach_errors,
    recent_errors: c.attach_errors ? recentErrors() : [],
    include_paypal: c.include_paypal,
    include_financial: c.include_financial,
    conversation: c.include_financial ? (c.conversation ?? []).slice(-8) : [],
  };
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
const page = () => (typeof window === "undefined" ? null : window.location.pathname.slice(0, 300));
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || "web";

export const supportDesk = {
  assist: (a: AccountInfo, question: string, opts: { ticket?: boolean; page?: string | null } = {}) =>
    runtimeCall<AssistAnswer>(a, "/support/assist", json("POST", { question, page: opts.page ?? page(), app: "web", version: APP_VERSION, ticket: !!opts.ticket })),
  paypal: (a: AccountInfo) => runtimeCall<PayPalHelp>(a, "/support/paypal"),
  create: (a: AccountInfo, t: { subject: string; category: TicketCategory; body: string; page?: string | null }, c: Consent) =>
    runtimeCall<{ ticket: Ticket; created: boolean }>(
      a,
      "/support/tickets",
      json("POST", { ...t, page: t.page ?? page(), app: "web", version: APP_VERSION, ...consentBody(c) }),
    ),
  fromCard: (a: AccountInfo, action: RtProposedAction, c: Consent, details?: string) =>
    runtimeCall<{ ticket: Ticket; created: boolean }>(a, "/support/tickets/from-card", json("POST", { action, details: details || null, ...consentBody(c) })),
  mine: (a: AccountInfo, status?: TicketStatus) => runtimeCall<TicketPage>(a, `/support/tickets${status ? `?status=${status}` : ""}`),
  thread: (a: AccountInfo, id: string) => runtimeCall<TicketThread>(a, `/support/tickets/${encodeURIComponent(id)}`),
  reply: (a: AccountInfo, id: string, body: string) => runtimeCall<TicketThread>(a, `/support/tickets/${encodeURIComponent(id)}/messages`, json("POST", { body })),
  admin: {
    list: (a: AccountInfo, p: { status?: TicketStatus | ""; q?: string; page?: number } = {}) => {
      const qs = new URLSearchParams();
      if (p.status) qs.set("status", p.status);
      if (p.q) qs.set("q", p.q);
      if (p.page && p.page > 1) qs.set("page", String(p.page));
      const s = qs.toString();
      return runtimeCall<AdminTicketPage>(a, `/admin/support/tickets${s ? `?${s}` : ""}`);
    },
    thread: (a: AccountInfo, id: string) => runtimeCall<TicketThread>(a, `/admin/support/tickets/${encodeURIComponent(id)}`),
    reply: (a: AccountInfo, id: string, body: { body: string; internal: boolean; email_user: boolean }) =>
      runtimeCall<AdminReply>(a, `/admin/support/tickets/${encodeURIComponent(id)}/messages`, json("POST", body)),
    status: (a: AccountInfo, id: string, status: TicketStatus) => runtimeCall<Ticket>(a, `/admin/support/tickets/${encodeURIComponent(id)}`, json("PATCH", { status })),
  },
};
