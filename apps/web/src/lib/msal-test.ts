"use client";

import type { AccountInfo, AuthenticationResult, IPublicClientApplication } from "@azure/msal-browser";

/**
 * Test-mode sign-in (NEXT_PUBLIC_TEST_MODE=1 builds only; see msal.ts). No network: "signing in" sets a flag in
 * localStorage and reloads, as the real redirect would; every token is the literal "test-token". A runtime started
 * with ACCNOMOS_TEST_MODE=1 uses its fakes and never forwards it; any other runtime would pass it to Microsoft,
 * which rejects it.
 */
const SIGNED_IN = "msal.accnomos-test.signedIn"; // "msal." like the real cache: Settings shows it, Disconnect clears it

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

function token(scopes: string[]): AuthenticationResult {
  return { accessToken: "test-token", account: TEST_ACCOUNT, scopes } as unknown as AuthenticationResult;
}

/** Just the IPublicClientApplication members the app calls. */
export function createTestMsal(): IPublicClientApplication {
  const fake = {
    handleRedirectPromise: async () => null,
    getActiveAccount: () => (signedIn() ? TEST_ACCOUNT : null),
    getAllAccounts: () => (signedIn() ? [TEST_ACCOUNT] : []),
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
    acquireTokenSilent: async ({ scopes }: { scopes: string[] }) => {
      if (!signedIn()) throw new Error("not signed in");
      return token(scopes);
    },
    acquireTokenRedirect: async () => {},
  };
  return fake as unknown as IPublicClientApplication;
}
