"use client";

import type { AccountInfo, AuthenticationResult, IPublicClientApplication } from "@azure/msal-browser";

/**
 * Test-mode sign-in (NEXT_PUBLIC_TEST_MODE=1 builds only; see msal.ts). No network: "signing in" sets a flag in
 * localStorage and reloads, as the real redirect would. A runtime started with ACCNOMOS_TEST_MODE=1 uses its fakes
 * and never forwards a token; any other runtime would pass it to Microsoft, which rejects it.
 *
 * Several accounts, like MSAL's multi-account cache (linked profiles, lib/profiles.ts): the first is Sam (token
 * "test-token"); signing in again while signed in adds Jo, a second Microsoft account whose token
 * "test-token.jo" the runtime gives a OneDrive of its own (services/runtime/app/testmode.py TEST_ACCOUNT_TOKEN).
 */
const SIGNED_IN = "msal.accnomos-test.signedIn"; // "msal." like the real cache: Settings shows it, Disconnect clears it
const ACCOUNTS = "msal.accnomos-test.accounts"; // JSON list of signed-in test account keys, in sign-in order
const ACTIVE = "msal.accnomos-test.active";

export const TEST_ACCOUNT: AccountInfo = {
  homeAccountId: "test-home.9188040d-6c67-4c5b-b112-36a304b66dad",
  environment: "login.test.invalid",
  tenantId: "9188040d-6c67-4c5b-b112-36a304b66dad", // a personal account: books in OneDrive › Apps › Accnomos
  username: "sam@sambuilds.example",
  localAccountId: "test-local",
  name: "Sam Builder (test)",
};

export const TEST_ACCOUNT_2: AccountInfo = {
  homeAccountId: "test-home-jo.9188040d-6c67-4c5b-b112-36a304b66dad",
  environment: "login.test.invalid",
  tenantId: "9188040d-6c67-4c5b-b112-36a304b66dad",
  username: "jo@personal.example",
  localAccountId: "test-local-jo",
  name: "Jo Builder (test)",
};

const ALL: Record<string, { account: AccountInfo; token: string }> = {
  sam: { account: TEST_ACCOUNT, token: "test-token" },
  jo: { account: TEST_ACCOUNT_2, token: "test-token.jo" },
};

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Signed-in keys; the old single flag (e2e/fixtures.ts signIn) means Sam alone. */
function signedInKeys(): string[] {
  if (read(SIGNED_IN) !== "1") return [];
  try {
    const keys = JSON.parse(read(ACCOUNTS) ?? '["sam"]') as unknown;
    const ok = Array.isArray(keys) ? keys.filter((k): k is string => typeof k === "string" && k in ALL) : [];
    return ok.length ? ok : ["sam"];
  } catch {
    return ["sam"];
  }
}

function keyOf(account: AccountInfo | null | undefined): string | undefined {
  return Object.keys(ALL).find((k) => ALL[k].account.homeAccountId === account?.homeAccountId);
}

function save(keys: string[], active: string | undefined): void {
  if (!keys.length) {
    window.localStorage.removeItem(SIGNED_IN);
    window.localStorage.removeItem(ACCOUNTS);
    window.localStorage.removeItem(ACTIVE);
    return;
  }
  window.localStorage.setItem(SIGNED_IN, "1");
  window.localStorage.setItem(ACCOUNTS, JSON.stringify(keys));
  if (active) window.localStorage.setItem(ACTIVE, active);
}

function active(): AccountInfo | null {
  const keys = signedInKeys();
  const key = read(ACTIVE);
  return key && keys.includes(key) ? ALL[key].account : null;
}

/** Just the IPublicClientApplication members the app calls. */
export function createTestMsal(): IPublicClientApplication {
  const fake = {
    handleRedirectPromise: async () => null,
    getActiveAccount: () => active(),
    getAllAccounts: () => signedInKeys().map((k) => ALL[k].account),
    setActiveAccount: (account: AccountInfo | null) => {
      const key = keyOf(account);
      if (key && signedInKeys().includes(key)) window.localStorage.setItem(ACTIVE, key);
    },
    loginRedirect: async () => {
      const keys = signedInKeys();
      const next = Object.keys(ALL).find((k) => !keys.includes(k)) ?? keys[0] ?? "sam"; // "select_account": the next one
      save(keys.includes(next) ? keys : [...keys, next], next);
      window.location.reload();
      await new Promise(() => {}); // like a real redirect, never resolves
    },
    logoutRedirect: async (request?: { account?: AccountInfo | null }) => {
      const gone = keyOf(request?.account);
      const keys = gone ? signedInKeys().filter((k) => k !== gone) : [];
      save(keys, keys[0]);
      window.location.assign(window.location.origin);
      await new Promise(() => {});
    },
    acquireTokenSilent: async ({ scopes, account }: { scopes: string[]; account?: AccountInfo }) => {
      const key = keyOf(account) ?? read(ACTIVE) ?? signedInKeys()[0];
      if (!key || !signedInKeys().includes(key)) throw new Error("not signed in");
      return { accessToken: ALL[key].token, account: ALL[key].account, scopes } as unknown as AuthenticationResult;
    },
    acquireTokenRedirect: async () => {},
  };
  return fake as unknown as IPublicClientApplication;
}
