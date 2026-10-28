"use client";

import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";

/**
 * Microsoft sign-in for Accnomos (public client, PKCE, no secret). Tokens live only in this browser.
 * Scopes are requested incrementally (decision H26): sign-in + storage first; mail/calendar when first used.
 * The library (68 kB gzipped) is imported on first use, so it is in no page's first-load JS (docs/PERF.md);
 * keep every other import of @azure/msal-browser type-only.
 */
export const SIGN_IN_SCOPES = ["User.Read", "offline_access"];
export const STORAGE_SCOPES = ["Files.ReadWrite.AppFolder"]; // personal accounts
export const STORAGE_SCOPES_WORK = ["Files.ReadWrite"]; // work/school accounts (AppFolder is MSA-only)
export const MAIL_SCOPES = ["Mail.ReadWrite", "Mail.Send"];
export const CALENDAR_SCOPES = ["Calendars.ReadWrite"]; // asked for only when the user applies a day plan
export const CALENDAR_READ_SCOPES = ["Calendars.Read"]; // asked for the first time the user plans a day

const clientId = process.env.NEXT_PUBLIC_MS_CLIENT_ID ?? "";
const authority = process.env.NEXT_PUBLIC_MS_AUTHORITY ?? "https://login.microsoftonline.com/common";

let instancePromise: Promise<IPublicClientApplication> | null = null;

/** lib/demo.ts's session key, read here directly so this module does not import demo.ts eagerly. */
function isDemo(): boolean {
  try {
    return typeof window !== "undefined" && !!window.localStorage.getItem("msal.accnomos-demo.session");
  } catch {
    return false;
  }
}

// `process.env.NEXT_PUBLIC_TEST_MODE === "1"` is written out at each use (not shared as a constant) so the
// bundler folds it: only a `NEXT_PUBLIC_TEST_MODE=1` build (e2e/build.mjs) contains the fake sign-in, msal-test.ts.
export function msalConfigured(): boolean {
  return process.env.NEXT_PUBLIC_TEST_MODE === "1" || clientId.length > 0 || isDemo();
}

export function getMsal(): Promise<IPublicClientApplication> {
  // A demo sandbox (lib/demo.ts) on this device: its fake stands in for MSAL, in every build.
  if (!instancePromise && isDemo()) {
    instancePromise = import("./demo").then((m) => m.createDemoMsal());
  }
  if (process.env.NEXT_PUBLIC_TEST_MODE === "1" && !instancePromise) {
    instancePromise = import("./msal-test").then((m) => m.createTestMsal());
  }
  if (!instancePromise) {
    instancePromise = import("@azure/msal-browser").then((m) =>
      m.createStandardPublicClientApplication({
        auth: {
          clientId,
          authority,
          redirectUri: `${window.location.origin}/auth/callback.html`,
          postLogoutRedirectUri: window.location.origin,
        },
        cache: { cacheLocation: "localStorage" },
      }),
    );
  }
  return instancePromise;
}

/** Personal Microsoft accounts carry this tenant id; work/school accounts don't. */
export const MSA_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad";

export function isPersonalAccount(account: AccountInfo): boolean {
  return account.tenantId === MSA_TENANT;
}

export function storageScopesFor(account: AccountInfo): string[] {
  return isPersonalAccount(account) ? STORAGE_SCOPES : STORAGE_SCOPES_WORK;
}

export type AccountKind = "personal" | "work";

export function accountKind(account: AccountInfo): AccountKind {
  return isPersonalAccount(account) ? "personal" : "work";
}

/**
 * Outlook intake (F10) reads mail, nothing more. Same scope for personal and work accounts; requested only
 * when the user turns intake on (H26), always together with the storage scopes so one token covers both.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function mailScopesFor(kind: AccountKind): string[] {
  return ["Mail.Read"];
}

/**
 * Inbox triage › *Draft in Outlook* saves a reply in the user's Drafts. Asked for only when the user first taps
 * it (H26), together with the storage scopes (the runtime writes an audit line). Nothing is ever sent.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function mailDraftScopesFor(kind: AccountKind): string[] {
  return ["Mail.ReadWrite"];
}

/**
 * Contacts › Import from Outlook reads the address book, nothing more. Requested only when the user taps
 * Import (H26), together with the storage scopes, because the import also writes contacts.json to OneDrive.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function contactsScopesFor(kind: AccountKind): string[] {
  return ["Contacts.Read"];
}

/**
 * Sending an invoice or a reminder from the user's Outlook. Asked for only when the user first taps Send in a
 * confirmation dialog (H26), together with the storage scopes, as the runtime also saves the sent copy.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function mailSendScopesFor(kind: AccountKind): string[] {
  return ["Mail.Send"];
}

/** Access token for the given scopes; falls back to an interactive redirect when consent is needed. */
export async function getToken(scopes: string[]): Promise<string> {
  const msal = await getMsal();
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  if (!account) throw new Error("not signed in");
  try {
    const result = await msal.acquireTokenSilent({ scopes, account });
    return result.accessToken;
  } catch (e) {
    const { InteractionRequiredAuthError } = await import("@azure/msal-browser");
    if (e instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ scopes, account });
      throw new Error("redirecting for consent");
    }
    throw e;
  }
}

/**
 * Settings › Email intake: more mailboxes. Another Microsoft account is a second account in the same MSAL cache
 * (its own popup sign-in, `prompt: select_account`), asked for `Mail.Read` only: never its OneDrive, never Send.
 * A shared mailbox is read with the signed-in work account's `Mail.Read.Shared` (delegated; work or school accounts
 * only; https://learn.microsoft.com/graph/permissions-reference#mailreadshared).
 */
export const LINKED_MAIL_SCOPES = ["Mail.Read"];
export const SHARED_MAIL_SCOPES = ["Mail.Read.Shared"];

/** The account the books belong to. Linked mailboxes share the cache, so never just `getAllAccounts()[0]`. */
export function primaryAccount(msal: IPublicClientApplication): AccountInfo | null {
  return msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
}

/** Accounts (homeAccountId) signed in here only to read a linked mailbox: not sets of books, so not profiles. */
const MAILBOX_ACCOUNTS = "accnomos.mailbox-accounts";

export function mailboxOnlyAccounts(): string[] {
  try {
    const ids = JSON.parse(window.localStorage.getItem(MAILBOX_ACCOUNTS) ?? "[]") as unknown;
    return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function markMailboxAccount(id: string, on: boolean): void {
  const ids = mailboxOnlyAccounts().filter((x) => x !== id);
  try {
    window.localStorage.setItem(MAILBOX_ACCOUNTS, JSON.stringify(on ? [...ids, id] : ids));
  } catch {
    /* storage unavailable: the profile menu may list the mailbox's account */
  }
}

/** The cached account signed in as `address` (a linked mailbox), if any. */
export function linkedAccount(msal: IPublicClientApplication, address: string): AccountInfo | null {
  const want = address.trim().toLowerCase();
  return msal.getAllAccounts().find((a) => a.username.toLowerCase() === want) ?? null;
}

/**
 * Sign in to one more Microsoft account in a popup and return it. The signed-in account stays the active one, so
 * the books, and every other token, keep coming from it.
 */
export async function signInExtraAccount(loginHint?: string): Promise<AccountInfo> {
  const msal = await getMsal();
  const primary = primaryAccount(msal);
  if (!primary) throw new Error("not signed in");
  msal.setActiveAccount(primary);
  try {
    const result = await msal.loginPopup({ scopes: LINKED_MAIL_SCOPES, prompt: "select_account", ...(loginHint ? { loginHint } : {}) });
    if (!result.account) throw new Error("Microsoft did not say which account signed in");
    if (result.account.homeAccountId !== primary.homeAccountId) markMailboxAccount(result.account.homeAccountId, true);
    return result.account;
  } finally {
    msal.setActiveAccount(primary);
  }
}

/**
 * A linked mailbox's token without any prompt, or null when it needs the user (sign in again, or consent).
 * Never redirects: a check of several mailboxes must not leave the page halfway.
 */
export async function mailboxTokenSilent(kind: "microsoft" | "shared", address: string): Promise<string | null> {
  const msal = await getMsal();
  const account = kind === "shared" ? primaryAccount(msal) : linkedAccount(msal, address);
  if (!account) return null;
  try {
    const scopes = kind === "shared" ? SHARED_MAIL_SCOPES : LINKED_MAIL_SCOPES;
    return (await msal.acquireTokenSilent({ scopes, account })).accessToken;
  } catch {
    return null;
  }
}

/** Forget a linked account's tokens in this browser (never the signed-in one). */
export async function forgetExtraAccount(address: string): Promise<void> {
  const msal = await getMsal();
  const account = linkedAccount(msal, address);
  const primary = primaryAccount(msal);
  if (!account || (primary && account.homeAccountId === primary.homeAccountId)) return;
  await msal.clearCache({ account });
  markMailboxAccount(account.homeAccountId, false);
  if (primary) msal.setActiveAccount(primary);
}
