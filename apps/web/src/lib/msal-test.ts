"use client";

import type { AccountInfo, AuthenticationResult, IPublicClientApplication } from "@azure/msal-browser";

/**
 * Test-mode sign-in (NEXT_PUBLIC_TEST_MODE=1 builds only; see msal.ts). No network: "signing in" sets a flag in
 * localStorage and reloads, as the real redirect would; every token is the literal "test-token". A runtime started
 * with ACCNOMOS_TEST_MODE=1 uses its fakes and never forwards it; any other runtime would pass it to Microsoft,
 * which rejects it.
 */
const SIGNED_IN = "msal.accnomos-test.signedIn"; // "msal." like the real cache: Settings shows it, Disconnect clears it
/** Extra accounts signed in through `loginPopup` (Settings › Email intake), as usernames. */
const LINKED = "msal.accnomos-test.linked";
/** Who the next popup signs in as; a spec may set it first. */
export const POPUP_ACCOUNT = "msal.accnomos-test.popup";
export const DEFAULT_POPUP_ACCOUNT = "receipts@sambuilds-mail.example";

export const TEST_ACCOUNT: AccountInfo = {
  homeAccountId: "test-home.9188040d-6c67-4c5b-b112-36a304b66dad",
  environment: "login.test.invalid",
  tenantId: "9188040d-6c67-4c5b-b112-36a304b66dad", // a personal account: books in OneDrive › Apps › Accnomos
  username: "sam@sambuilds.example",
  localAccountId: "test-local",
  name: "Sam Builder (test)",
};

function signedIn(): boolean {
  try {
    return window.localStorage.getItem(SIGNED_IN) === "1";
  } catch {
    return false;
  }
}

function linked(): string[] {
  try {
    return JSON.parse(window.localStorage.getItem(LINKED) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function setLinked(names: string[]): void {
  window.localStorage.setItem(LINKED, JSON.stringify(names));
}

/** A second (fake) Microsoft account: a work account in its own tenant. */
function extraAccount(username: string): AccountInfo {
  return {
    homeAccountId: `test-home-${username}.test-tenant`,
    environment: "login.test.invalid",
    tenantId: "test-tenant",
    username,
    localAccountId: `test-local-${username}`,
    name: username,
  };
}

function token(scopes: string[], account: AccountInfo = TEST_ACCOUNT): AuthenticationResult {
  return { accessToken: "test-token", account, scopes } as unknown as AuthenticationResult;
}

/** Just the IPublicClientApplication members the app calls. */
export function createTestMsal(): IPublicClientApplication {
  const fake = {
    handleRedirectPromise: async () => null,
    getActiveAccount: () => (signedIn() ? TEST_ACCOUNT : null),
    getAllAccounts: () => (signedIn() ? [TEST_ACCOUNT, ...linked().map(extraAccount)] : []),
    setActiveAccount: () => {},
    loginRedirect: async () => {
      window.localStorage.setItem(SIGNED_IN, "1");
      window.location.reload();
      await new Promise(() => {}); // like a real redirect, never resolves
    },
    logoutRedirect: async () => {
      window.localStorage.removeItem(SIGNED_IN);
      window.location.assign(window.location.origin);
      await new Promise(() => {});
    },
    acquireTokenSilent: async ({ scopes, account }: { scopes: string[]; account?: AccountInfo }) => {
      if (!signedIn()) throw new Error("not signed in");
      if (account && account.homeAccountId !== TEST_ACCOUNT.homeAccountId) {
        if (!linked().includes(account.username)) throw new Error("interaction_required: account not in the cache");
        return token(scopes, account);
      }
      return token(scopes);
    },
    loginPopup: async () => {
      if (!signedIn()) throw new Error("not signed in");
      const username = window.localStorage.getItem(POPUP_ACCOUNT) || DEFAULT_POPUP_ACCOUNT;
      if (!linked().includes(username)) setLinked([...linked(), username]);
      return token(["Mail.Read"], username === TEST_ACCOUNT.username ? TEST_ACCOUNT : extraAccount(username));
    },
    clearCache: async ({ account }: { account?: AccountInfo } = {}) => {
      if (account) setLinked(linked().filter((u) => u !== account.username));
    },
    acquireTokenRedirect: async () => {},
  };
  return fake as unknown as IPublicClientApplication;
}
