"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, mailboxOnlyAccounts } from "./msal";
import type { RtProfile, RtProfileKind } from "./runtime";

/**
 * Linked profiles. One Microsoft account is one set of books (a company, a sole-trader business or personal
 * finances); a user links several by signing in to each, and MSAL's multi-account cache keeps them all. The active
 * account is the profile: every runtime and Graph call uses its token (getToken in msal.ts), so books never mix.
 * There is no server-side list: this browser keeps it (`accnomos.profiles`), and each account's own books hold its
 * name and kind (`_System/profile.json`, GET/PUT /profile).
 *
 * Settings this browser keeps for "the business" (VAT stagger, HMRC connection, Ask history, intake…) belong to one
 * profile, so switching stashes the current profile's copy under its account and restores the other's
 * (PROFILE_KEYS). Nothing else on the device changes: the AI settings and device id are the user's, not a business's.
 */

const STATE_KEY = "accnomos.profiles";
const STASH_PREFIX = "accnomos.profile-data.";

/** Per-business keys in localStorage, kept per profile. */
export const PROFILE_KEYS = [
  "accnomos.business",
  "accnomos.business.vrn",
  "accnomos.vatPeriod",
  "accnomos.autopilot",
  "accnomos.ask-history",
  "accnomos.invoice-draft",
  "accnomos.intake.mail",
  "accnomos.intake.mail.last",
  "accnomos.triage.mail",
  "accnomos.triage.mail.last",
  "accnomos.triage.result",
  "accnomos.triage.pending-draft",
  "accnomos.setup.dismissed",
  "accnomos.setup.tried-receipt",
  "accnomos.setup.contacts-imported",
];

/** Session keys dropped on every switch, never copied: an HMRC connection belongs to one business. */
const SESSION_KEYS = ["accnomos.hmrc", "accnomos.hmrc.pending"];

/** What the menu shows for a profile it cannot ask right now (another account's books). */
export interface ProfileMeta {
  name: string;
  kind: RtProfileKind;
  features: string[];
  exists: boolean;
}

interface State {
  /** The account whose copy of PROFILE_KEYS is live in localStorage now; null while another is being added. */
  owner: string | null;
  /** Account (homeAccountId) the user started "Add another account" from; cleared once the new one is in. */
  addingFrom?: string | null;
  meta: Record<string, ProfileMeta>;
}

export const KIND_LABEL: Record<RtProfileKind, string> = {
  company: "Company",
  sole_trader: "Sole trader",
  landlord: "Landlord",
  partnership: "Partnership",
  personal: "Personal",
};

function readState(): State | null {
  try {
    const raw = window.localStorage.getItem(STATE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<State>;
    return { owner: typeof s.owner === "string" ? s.owner : null, addingFrom: s.addingFrom ?? null, meta: s.meta ?? {} };
  } catch {
    return null;
  }
}

function writeState(s: State): void {
  try {
    window.localStorage.setItem(STATE_KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: switching still works, settings are just not kept apart */
  }
  window.dispatchEvent(new Event(PROFILE_EVENT));
}

/** Fired when the profile list or the current profile's details change (the nav re-reads its features). */
export const PROFILE_EVENT = "accnomos:profiles";

function stash(id: string): void {
  try {
    const data: Record<string, string> = {};
    for (const k of PROFILE_KEYS) {
      const v = window.localStorage.getItem(k);
      if (v !== null) data[k] = v;
    }
    window.localStorage.setItem(STASH_PREFIX + id, JSON.stringify(data));
  } catch {
    /* nothing to keep */
  }
}

function clearLive(): void {
  try {
    for (const k of PROFILE_KEYS) window.localStorage.removeItem(k);
    // HMRC's sign-in lives in sessionStorage (lib/hmrc.ts) and is never carried to another profile: the user
    // connects HMRC again for that business.
    for (const k of SESSION_KEYS) window.sessionStorage.removeItem(k);
  } catch {
    /* nothing to clear */
  }
}

/** Put `id`'s stashed copy live (nothing stashed: an empty copy, a new profile starts from defaults). */
function restore(id: string): void {
  clearLive();
  try {
    const data = JSON.parse(window.localStorage.getItem(STASH_PREFIX + id) ?? "{}") as Record<string, string>;
    for (const [k, v] of Object.entries(data)) if (PROFILE_KEYS.includes(k)) window.localStorage.setItem(k, v);
  } catch {
    /* an unreadable stash: start from defaults */
  }
}

/**
 * Make localStorage hold `active`'s settings. The first time (no state yet) the live settings are taken to be the
 * active account's, so nothing changes for anyone who used the app before profiles. True when it swapped something
 * in, so the caller reloads and every page reads the right copy.
 */
export function reconcile(activeId: string): boolean {
  const s = readState();
  if (!s) {
    writeState({ owner: activeId, meta: {} });
    return false;
  }
  if (s.owner === activeId) {
    if (s.addingFrom) writeState({ ...s, addingFrom: null });
    return false;
  }
  if (s.owner) stash(s.owner);
  restore(activeId);
  writeState({ ...s, owner: activeId, addingFrom: null });
  return true;
}

/** The current profile's features, from what was last read (null when not known yet: show everything). */
export function currentFeatures(): string[] | null {
  const s = readState();
  return s?.owner ? (s.meta[s.owner]?.features ?? null) : null;
}

/** The current profile's details as last read (kind decides the Personal menu), or undefined. */
export function currentMeta(): ProfileMeta | undefined {
  const s = readState();
  return s?.owner ? s.meta[s.owner] : undefined;
}

export function profileMeta(id: string): ProfileMeta | undefined {
  return readState()?.meta[id];
}

export function rememberProfile(id: string, p: RtProfile): void {
  const s = readState() ?? { owner: id, meta: {} };
  const meta: ProfileMeta = { name: p.name, kind: p.kind, features: p.features, exists: p.exists };
  const before = s.meta[id];
  if (before && JSON.stringify(before) === JSON.stringify(meta)) return;
  writeState({ ...s, meta: { ...s.meta, [id]: meta } });
}

/** Whether the user is in the middle of adding an account, started from `activeId` (the Connect page asks). */
export function addingFrom(): string | null {
  return readState()?.addingFrom ?? null;
}

/** One click in the menu: the other account's token from now on, and its settings in this browser. */
export async function switchTo(account: AccountInfo): Promise<void> {
  const msal = await getMsal();
  msal.setActiveAccount(account);
  reconcile(account.homeAccountId);
  window.location.reload();
}

/** "Add another account / business": keep this profile's settings aside; the caller then opens /connect?add=1,
 *  where the user signs in with the other account. */
export function startAdding(fromId: string): void {
  const s = readState() ?? { owner: fromId, meta: {} };
  if (s.owner) stash(s.owner);
  writeState({ ...s, addingFrom: fromId });
}

/** "Sign out of this one": forget this browser's copy of its settings, then sign that account out of MSAL. */
export async function signOutOf(account: AccountInfo): Promise<void> {
  const s = readState();
  if (s) {
    const meta = { ...s.meta };
    delete meta[account.homeAccountId];
    writeState({ ...s, owner: s.owner === account.homeAccountId ? null : s.owner, meta });
  }
  try {
    window.localStorage.removeItem(STASH_PREFIX + account.homeAccountId);
  } catch {
    /* nothing kept */
  }
  if (s?.owner === account.homeAccountId) clearLive(); // the next account's copy is put back by reconcile()
  const msal = await getMsal();
  await msal.logoutRedirect({ account, postLogoutRedirectUri: window.location.origin });
}

/** The sign-ins this browser holds, active one first. An account signed in only to read a linked mailbox (Settings ›
 * Email intake) shares MSAL's cache but is not a set of books, so it is left out unless it is also a profile. */
export async function linkedAccounts(): Promise<{ active: AccountInfo | null; all: AccountInfo[] }> {
  const msal = await getMsal();
  const mailboxOnly = new Set(mailboxOnlyAccounts());
  const known = readState()?.meta ?? {};
  const current = msal.getActiveAccount();
  const all = msal
    .getAllAccounts()
    .filter((a) => !mailboxOnly.has(a.homeAccountId) || a.homeAccountId === current?.homeAccountId || a.homeAccountId in known);
  const active = current ?? all[0] ?? null;
  return { active, all };
}
