"use client";

import type { AccountInfo, AuthenticationResult, IPublicClientApplication } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";

/**
 * The demo sandbox (services/runtime/app/demo.py): the whole app on the sample books, with no Microsoft sign-in.
 *
 * `POST /demo/session` returns an opaque session id; this browser keeps it in localStorage under an `msal.` key, so
 * every page treats the device as signed in (and Settings › Disconnect clears it like a real sign-in). While it is
 * there, getMsal() hands out the fake below instead of MSAL: its one account is the demo visitor, and its "token" is
 * the session id, which runtimeHeaders() sends as `X-Demo-Session` and graph.ts sends to the runtime's Graph
 * look-alike. Nothing in a demo talks to Microsoft or HMRC, and nothing is ever emailed.
 */
export const DEMO_KEY = "msal.accnomos-demo.session";
export const DEMO_HEADER = "X-Demo-Session";
export const DEMO_TOKEN_PREFIX = "demo:";
export const DEMO_EVENT = "accnomos:demo";
/** What the web app says wherever a signed-in user would see "Sent". */
export const NOT_SENT = "Sent (demo — not actually sent)";

/** A "sent" message as the user sees it: in a demo, led by NOT_SENT, because nothing was emailed. */
export function sentNote(text: string): string {
  return isDemo() ? `${NOT_SENT} · ${text}` : text;
}

export interface DemoSession {
  session: string;
  business: string;
  label: string;
  user: string;
  today: string;
  idle_ttl_s: number;
  started_at: number;
}

export const DEMO_ACCOUNT: AccountInfo = {
  homeAccountId: "demo-home.9188040d-6c67-4c5b-b112-36a304b66dad",
  environment: "demo.accnomos.invalid",
  tenantId: "9188040d-6c67-4c5b-b112-36a304b66dad", // a personal account: books in "OneDrive › Apps › Accnomos"
  username: "demo@accnomos.example",
  localAccountId: "demo-local",
  name: "Demo visitor",
};

export function demoSession(): DemoSession | null {
  try {
    const raw = window.localStorage.getItem(DEMO_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as DemoSession;
    return typeof s?.session === "string" && s.session ? s : null;
  } catch {
    return null;
  }
}

export function isDemo(): boolean {
  return typeof window !== "undefined" && demoSession() !== null;
}

/** The runtime's error detail, or a plain sentence. */
async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return fallback;
}

/**
 * Start a fresh demo (or, in one, Reset demo: the runtime drops the old session). Resolves once the sample books are
 * ready; the first visitor of the day may wait while they are seeded.
 */
export async function startDemo(): Promise<DemoSession> {
  const old = demoSession();
  let res: Response;
  try {
    res = await fetch(`${RUNTIME_URL}/demo/session`, {
      method: "POST",
      headers: old ? { [DEMO_HEADER]: old.session } : {},
    });
  } catch {
    throw new Error("Couldn't reach the Accnomos server to start the demo. Check you're online and try again.");
  }
  if (res.status === 404) throw new Error("The demo sandbox isn't switched on for this server.");
  if (!res.ok) throw new Error(await detail(res, `The demo couldn't start (${res.status}). Try again in a minute.`));
  const body = (await res.json()) as Omit<DemoSession, "started_at">;
  const session: DemoSession = { ...body, started_at: Date.now() };
  try {
    window.localStorage.setItem(DEMO_KEY, JSON.stringify(session));
    // The HMRC (simulated) connection from an earlier demo belongs to that demo.
    window.sessionStorage.removeItem("accnomos.hmrc");
  } catch {
    throw new Error("This browser won't keep the demo session (storage is blocked). Allow site data and try again.");
  }
  window.dispatchEvent(new Event(DEMO_EVENT));
  return session;
}

/** Forget the demo on this device (and tell the runtime, best effort), then go to `next`. */
export async function leaveDemo(next = "/connect"): Promise<void> {
  const s = demoSession();
  if (s) {
    try {
      await fetch(`${RUNTIME_URL}/demo/session`, { method: "DELETE", headers: { [DEMO_HEADER]: s.session } });
    } catch {
      /* it expires on its own after 2 hours idle */
    }
  }
  try {
    window.localStorage.removeItem(DEMO_KEY);
    window.sessionStorage.removeItem("accnomos.hmrc");
  } catch {
    /* nothing kept */
  }
  window.location.assign(next);
  await new Promise(() => {}); // like a redirect, never resolves
}

/** Is this demo session still alive on the runtime? false once it has expired (2 hours idle) or was reset elsewhere. */
export async function demoAlive(): Promise<boolean | null> {
  const s = demoSession();
  if (!s) return false;
  try {
    const res = await fetch(`${RUNTIME_URL}/demo/session`, { headers: { [DEMO_HEADER]: s.session } });
    return res.ok ? true : res.status === 401 ? false : null;
  } catch {
    return null; // offline: say nothing
  }
}

/** Graph headers for a token from getToken(): the demo's session header, or a Microsoft bearer token. */
export function graphAuthHeaders(token: string): Record<string, string> {
  return token.startsWith(DEMO_TOKEN_PREFIX)
    ? { [DEMO_HEADER]: token.slice(DEMO_TOKEN_PREFIX.length) }
    : { Authorization: `Bearer ${token}` };
}

/** Just the IPublicClientApplication members the app calls (as msal-test.ts). */
export function createDemoMsal(): IPublicClientApplication {
  const account = () => (demoSession() ? DEMO_ACCOUNT : null);
  const fake = {
    handleRedirectPromise: async () => null,
    getActiveAccount: account,
    getAllAccounts: () => (demoSession() ? [DEMO_ACCOUNT] : []),
    setActiveAccount: () => {},
    // "Sign in with Microsoft" from inside a demo: leave it, then sign in for real on /connect.
    loginRedirect: async () => leaveDemo("/connect"),
    logoutRedirect: async () => leaveDemo("/connect"),
    acquireTokenSilent: async ({ scopes }: { scopes: string[] }) => {
      const s = demoSession();
      if (!s) throw new Error("not signed in");
      return { accessToken: `${DEMO_TOKEN_PREFIX}${s.session}`, account: DEMO_ACCOUNT, scopes } as unknown as AuthenticationResult;
    },
    acquireTokenRedirect: async () => {},
  };
  return fake as unknown as IPublicClientApplication;
}
