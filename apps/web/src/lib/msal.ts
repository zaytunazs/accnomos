"use client";

import {
  createStandardPublicClientApplication,
  InteractionRequiredAuthError,
  type AccountInfo,
  type IPublicClientApplication,
} from "@azure/msal-browser";

/**
 * Microsoft sign-in for Accnomos (public client, PKCE, no secret). Tokens live only in this browser.
 * Scopes are requested incrementally (decision H26): sign-in + storage first; mail/calendar when first used.
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

// `process.env.NEXT_PUBLIC_TEST_MODE === "1"` is written out at each use (not shared as a constant) so the
// bundler folds it: only a `NEXT_PUBLIC_TEST_MODE=1` build (e2e/build.mjs) contains the fake sign-in, msal-test.ts.
export function msalConfigured(): boolean {
  return process.env.NEXT_PUBLIC_TEST_MODE === "1" || clientId.length > 0;
}

export function getMsal(): Promise<IPublicClientApplication> {
  if (process.env.NEXT_PUBLIC_TEST_MODE === "1" && !instancePromise) {
    instancePromise = import("./msal-test").then((m) => m.createTestMsal());
  }
  if (!instancePromise) {
    instancePromise = createStandardPublicClientApplication({
      auth: {
        clientId,
        authority,
        redirectUri: `${window.location.origin}/auth/callback.html`,
        postLogoutRedirectUri: window.location.origin,
      },
      cache: { cacheLocation: "localStorage" },
    });
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
    if (e instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ scopes, account });
      throw new Error("redirecting for consent");
    }
    throw e;
  }
}
