"use client";

/**
 * Accountant collaboration (services/runtime/app/accountant.py, portal.py, queries.py).
 *
 * An accountant who opens a client from /accountant sets the *client context* below (this tab only, sessionStorage).
 * While it is set, every runtime call carries X-Books-Drive-Id / X-Books-Item-Id / X-Books-Access, so the usual
 * pages (Home, Review, Bank, Reports, Audit, …) read the client's shared folder instead of the accountant's own
 * books; the runtime keeps each client's cache apart. Closing the tab, or "Back to your clients", clears it.
 */

export type ClientAccess = "read" | "edit";

export interface ClientContext {
  driveId: string;
  itemId: string;
  name: string;
  access: ClientAccess;
}

const KEY = "accnomos.client";
const CHANGED = "accnomos:client-changed";

export function getClientContext(): ClientContext | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as Partial<ClientContext>;
    if (typeof c.driveId !== "string" || typeof c.itemId !== "string" || !c.driveId || !c.itemId) return null;
    return { driveId: c.driveId, itemId: c.itemId, name: c.name ?? "", access: c.access === "edit" ? "edit" : "read" };
  } catch {
    return null;
  }
}

export function setClientContext(c: ClientContext | null): void {
  try {
    if (c) window.sessionStorage.setItem(KEY, JSON.stringify(c));
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* private mode: the context lasts as long as the page */
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function onClientContextChange(fn: () => void): () => void {
  window.addEventListener(CHANGED, fn);
  return () => window.removeEventListener(CHANGED, fn);
}

/** The runtime headers that point a call at a client's shared folder (none for your own books). */
export function clientHeaders(c: ClientContext | null): Record<string, string> {
  if (!c) return {};
  return { "X-Books-Drive-Id": c.driveId, "X-Books-Item-Id": c.itemId, "X-Books-Access": c.access };
}

/**
 * Graph scopes an accountant needs: items in another person's drive need an `.All` scope (Microsoft Learn,
 * drive: sharedWithMe, checked 28 Oct 2026). The portal only reads. Inside a client's books the token must also
 * write, even in a view-only client, because queries are written to `_System/queries`: what may change is decided
 * by the client's OneDrive permission and, for a view-only open, by the runtime's read-only guard.
 */
export const PORTAL_SCOPES = ["Files.Read.All"];
export const CLIENT_SCOPES = ["Files.ReadWrite.All"];

/**
 * Sharing the books folder: `driveItem: invite` needs Files.ReadWrite (not Files.ReadWrite.AppFolder). Personal
 * accounts are asked for it only when they invite someone; work accounts already have it.
 */
export const SHARE_SCOPES = ["Files.ReadWrite"];

// ---- wire types --------------------------------------------------------- //

export type ClientKind = "business" | "sole_trader" | "landlord" | "personal";

export const KIND_LABELS: Record<ClientKind, string> = {
  business: "Business",
  sole_trader: "Sole trader",
  landlord: "Landlord",
  personal: "Personal finances",
};

export interface RtClientProfile {
  name: string;
  kind: ClientKind;
  vat_registered: boolean;
  vat_start_month: number;
  vat_months: 1 | 3;
}

export interface RtInvitation {
  id: string;
  kind: "own" | "team";
  email: string;
  name: string;
  role: ClientAccess;
  method: "graph" | "manual";
  grants: { id: string; path: string; role: "read" | "write" }[];
  invited_at: string;
  invited_by: string;
  revoked_at: string | null;
  revoked_by: string | null;
  consent: { version: string; text_sha256: string; agreed_at: string; agreed_by: string } | null;
}

export interface RtAccountantSettings {
  invitations: RtInvitation[];
  profile: RtClientProfile | null;
  team_available: boolean;
  team_email: string | null;
  consent_version: string;
  consent_text: string[];
  client_code: string | null;
}

export interface RtClientSummary {
  drive_id: string;
  item_id: string;
  code: string;
  name: string;
  kind: ClientKind | null;
  owner: string | null;
  source: "shared_with_me" | "added" | "both";
  access: ClientAccess | null;
  review_waiting: number;
  needs_a_look: number;
  open_queries: number;
  waiting_on_client: number;
  waiting_on_you: number;
  last_activity: string | null;
  vat: { period: string; due: string; days_left: number } | null;
  vat_registered: boolean | null;
  error: string | null;
}

export interface RtPortal {
  clients: RtClientSummary[];
  shared_with_me_ok: boolean;
  note: string | null;
}

export type QuerySubjectKind = "transaction" | "document" | "proposal" | "bank_line" | "invoice" | "general";

export const SUBJECT_LABELS: Record<QuerySubjectKind, string> = {
  transaction: "A transaction",
  document: "A document",
  proposal: "A Review card",
  bank_line: "A bank line",
  invoice: "An invoice",
  general: "The books in general",
};

export interface RtQuery {
  id: string;
  subject: { kind: QuerySubjectKind; ref: string; label: string };
  status: "open" | "resolved";
  created_at: string;
  created_by: string;
  messages: { ts: string; author: string; role: "accountant" | "client"; text: string }[];
  resolved_at: string | null;
  resolved_by: string | null;
  waiting_on: "accountant" | "client" | null;
}

/** `?query=proposal:<id>:<label>` links from a Review card to a new query about it, on /accountant. */
export function queryLink(kind: QuerySubjectKind, ref: string, label: string): string {
  return `/accountant?query=${encodeURIComponent(`${kind}:${ref}:${label}`)}`;
}

export function parseQueryLink(raw: string | null): { kind: QuerySubjectKind; ref: string; label: string } | null {
  if (!raw) return null;
  const [kind, ref, ...rest] = raw.split(":");
  if (!(kind in SUBJECT_LABELS)) return null;
  return { kind: kind as QuerySubjectKind, ref: ref ?? "", label: rest.join(":") };
}
