"use client";

import type { AccountInfo, AuthenticationResult, IPublicClientApplication } from "@azure/msal-browser";

/**
 * Google sign-in for Accnomos: Google Identity Services' token client (`accounts.google.com/gsi/client`,
 * `google.accounts.oauth2.initTokenClient`), public client, no secret, tokens only in this browser.
 *
 * The books live in an `Accnomos` folder in the user's My Drive, through `drive.file` only: the app sees the files
 * it made, never the rest of the drive. Gmail, Calendar and Contacts are asked for at sign-in too (the scope list is
 * shared with the Android app and the runtime; see docs/GOOGLE_SETUP.md).
 *
 * The rest of the app speaks MSAL: `createGoogleMsal()` is a stand-in with just the IPublicClientApplication members
 * the app calls (as lib/demo.ts does), whose account is the Google user and whose access token is the Google one.
 * runtime.ts sends that token as `X-Graph-Token` with `X-Account-Kind: google`; lib/graph.ts reads and writes the
 * books folder through lib/gdrive.ts instead of Microsoft Graph.
 *
 * Google access tokens last an hour and the token model has no refresh token: when one is about to expire, a new one
 * is asked for with `prompt: "none"` and the user's email as `login_hint` (no screen shown when the grant is still
 * there). If Google wants the user (or the browser blocks the short-lived pop-up it uses), the call fails with
 * GOOGLE_SIGN_IN_AGAIN and the user signs in again from /connect.
 */
export const GOOGLE_SCOPES = [
  "openid",
  "email",
  "profile",
  "https://www.googleapis.com/auth/drive.file",
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.compose",
  "https://www.googleapis.com/auth/calendar.events",
  "https://www.googleapis.com/auth/contacts.readonly",
];
export const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";

/** localStorage key; the `msal.accnomos-` prefix makes lib/signed-in.ts count it as a sign-in, like the demo's. */
export const GOOGLE_SESSION_KEY = "msal.accnomos-google.session";
/** AccountInfo.environment of the stand-in account: how the rest of the app tells a Google account apart. */
export const GOOGLE_ENVIRONMENT = "accounts.google.com";
export const GOOGLE_SIGN_IN_AGAIN = "Your Google sign-in has expired. Sign in with Google again to carry on.";

const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const GSI_SRC = "https://accounts.google.com/gsi/client";
const USERINFO = "https://openidconnect.googleapis.com/v1/userinfo";
const EARLY_MS = 2 * 60 * 1000; // renew a token this long before Google says it expires

export interface GoogleSession {
  sub: string;
  email: string;
  name: string;
  token: string;
  expiresAt: number; // epoch ms
  scope: string;
}

/** Shown only when the site was built with NEXT_PUBLIC_GOOGLE_CLIENT_ID. */
export function googleConfigured(): boolean {
  return clientId.length > 0;
}

export function readGoogleSession(): GoogleSession | null {
  try {
    const raw = window.localStorage.getItem(GOOGLE_SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<GoogleSession>;
    if (typeof s.token !== "string" || typeof s.email !== "string" || typeof s.expiresAt !== "number") return null;
    return { sub: s.sub ?? s.email, email: s.email, name: s.name ?? "", token: s.token, expiresAt: s.expiresAt, scope: s.scope ?? "" };
  } catch {
    return null;
  }
}

function saveSession(s: GoogleSession | null): void {
  try {
    if (s) window.localStorage.setItem(GOOGLE_SESSION_KEY, JSON.stringify(s));
    else window.localStorage.removeItem(GOOGLE_SESSION_KEY);
  } catch {
    /* storage unavailable: the sign-in lasts for this page only */
  }
}

export function isGoogleAccount(account: AccountInfo | null | undefined): boolean {
  return account?.environment === GOOGLE_ENVIRONMENT;
}

function accountOf(s: GoogleSession): AccountInfo {
  return {
    homeAccountId: `google.${s.sub}`,
    environment: GOOGLE_ENVIRONMENT,
    tenantId: "google",
    username: s.email,
    localAccountId: s.sub,
    name: s.name || s.email,
  } as AccountInfo;
}

// ---------------------------------------------------------------------------------------------- Google Identity Services

interface TokenResponse {
  access_token?: string;
  expires_in?: number | string;
  scope?: string;
  error?: string;
  error_description?: string;
}
interface TokenClient {
  requestAccessToken(overrides?: { prompt?: string; login_hint?: string; scope?: string }): void;
}
interface GoogleOAuth2 {
  initTokenClient(config: {
    client_id: string;
    scope: string;
    include_granted_scopes?: boolean;
    prompt?: string;
    login_hint?: string;
    callback: (r: TokenResponse) => void;
    error_callback?: (e: { type?: string; message?: string }) => void;
  }): TokenClient;
  hasGrantedAllScopes(r: TokenResponse, first: string, ...rest: string[]): boolean;
  revoke(token: string, done?: () => void): void;
}
declare global {
  interface Window {
    google?: { accounts?: { oauth2?: GoogleOAuth2 } };
  }
}

let gsiPromise: Promise<GoogleOAuth2> | null = null;

/** Load the GIS script once. Call it early (when the sign-in button shows), so the click opens Google's window
 *  straight away: a pop-up opened after an await may be blocked. */
export function loadGoogle(): Promise<GoogleOAuth2> {
  if (window.google?.accounts?.oauth2) return Promise.resolve(window.google.accounts.oauth2);
  if (!gsiPromise) {
    gsiPromise = new Promise<GoogleOAuth2>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = GSI_SRC;
      script.async = true;
      script.onload = () => (window.google?.accounts?.oauth2 ? resolve(window.google.accounts.oauth2) : reject(new Error("Google sign-in did not load")));
      script.onerror = () => {
        gsiPromise = null;
        reject(new Error("Google sign-in could not be loaded. Check you're online and try again."));
      };
      document.head.appendChild(script);
    });
  }
  return gsiPromise;
}

/** One token request through GIS. `prompt`: "" first time / consent as needed, "none" silent, "select_account". */
function requestToken(oauth2: GoogleOAuth2, prompt: string, loginHint?: string): Promise<TokenResponse> {
  return new Promise((resolve, reject) => {
    const client = oauth2.initTokenClient({
      client_id: clientId,
      scope: GOOGLE_SCOPES.join(" "),
      include_granted_scopes: true,
      callback: (r) => (r.error || !r.access_token ? reject(new Error(r.error_description || r.error || "no token")) : resolve(r)),
      error_callback: (e) => reject(new Error(e.type || e.message || "google_error")),
    });
    client.requestAccessToken({ prompt, ...(loginHint ? { login_hint: loginHint } : {}) });
  });
}

async function sessionFrom(r: TokenResponse, previous?: GoogleSession | null): Promise<GoogleSession> {
  const token = r.access_token!;
  const expiresAt = Date.now() + Number(r.expires_in ?? 3600) * 1000;
  if (previous) return { ...previous, token, expiresAt, scope: r.scope ?? previous.scope };
  const res = await fetch(USERINFO, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error("Google did not say who signed in");
  const info = (await res.json()) as { sub?: string; email?: string; name?: string };
  if (!info.email) throw new Error("Google did not share your email address");
  return { sub: info.sub ?? info.email, email: info.email.toLowerCase(), name: info.name ?? "", token, expiresAt, scope: r.scope ?? "" };
}

/** "Continue with Google": Google's window, then the session saved here. Throws a sentence the page can show. */
export async function signInWithGoogle(): Promise<GoogleSession> {
  const oauth2 = await loadGoogle();
  const r = await requestToken(oauth2, "select_account");
  if (!oauth2.hasGrantedAllScopes(r, DRIVE_SCOPE)) {
    throw new Error("Accnomos needs permission to keep its own folder in your Google Drive. Sign in again and leave that box ticked.");
  }
  const session = await sessionFrom(r);
  saveSession(session);
  return session;
}

let renewing: Promise<GoogleSession> | null = null;

/** A token good for a few more minutes: the saved one, or a silent renewal (shared by every caller meanwhile). */
export async function googleToken(): Promise<string> {
  const s = readGoogleSession();
  if (!s) throw new Error("not signed in");
  if (s.expiresAt - Date.now() > EARLY_MS) return s.token;
  renewing ??= (async () => {
    try {
      const oauth2 = await loadGoogle();
      const fresh = await sessionFrom(await requestToken(oauth2, "none", s.email), s);
      saveSession(fresh);
      return fresh;
    } catch {
      throw new Error(GOOGLE_SIGN_IN_AGAIN);
    } finally {
      renewing = null;
    }
  })();
  return (await renewing).token;
}

/** Forget the sign-in on this device. Google's grant stays (myaccount.google.com/permissions removes it). */
export function forgetGoogle(): void {
  saveSession(null);
}

// ---------------------------------------------------------------------------------------------- the MSAL stand-in

/** Just the IPublicClientApplication members the app calls (as lib/demo.ts and lib/msal-test.ts). */
export function createGoogleMsal(): IPublicClientApplication {
  const account = () => {
    const s = readGoogleSession();
    return s ? accountOf(s) : null;
  };
  const leave = async (to: string) => {
    forgetGoogle();
    window.location.assign(to); // a full reload drops every signed-in state
    await new Promise(() => {});
  };
  const fake = {
    initialize: async () => {},
    handleRedirectPromise: async () => null,
    getActiveAccount: account,
    getAllAccounts: () => {
      const a = account();
      return a ? [a] : [];
    },
    setActiveAccount: () => {},
    // "Sign in with Microsoft" while signed in with Google: drop the Google sign-in first, then sign in on /connect.
    loginRedirect: async () => leave("/connect"),
    loginPopup: async () => {
      throw new Error("Extra Microsoft mailboxes need a Microsoft sign-in, not Google.");
    },
    logoutRedirect: async () => leave("/"),
    clearCache: async () => forgetGoogle(),
    acquireTokenSilent: async ({ scopes }: { scopes: string[] }) => {
      const a = account();
      if (!a) throw new Error("not signed in");
      const accessToken = await googleToken();
      return { accessToken, account: a, scopes } as unknown as AuthenticationResult;
    },
    acquireTokenRedirect: async () => leave("/connect"),
  };
  return fake as unknown as IPublicClientApplication;
}
