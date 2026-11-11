"use client";

/**
 * `track(name, props)`: first-party product analytics for the signed-in web app. Batched, no cookies, no third-party
 * script, nothing sent while Settings › Privacy has analytics off, in a demo sandbox or signed out. Counts, durations
 * and short labels only (lib/analytics-core.ts drops anything that looks like money, a name or an email).
 */
import { createTracker } from "./analytics-core";
import { APP_VERSION } from "./version";

export const OPT_OUT_KEY = "accnomos.analytics.optout";

export function analyticsOptedOut(): boolean {
  try {
    return window.localStorage.getItem(OPT_OUT_KEY) === "1";
  } catch {
    return false;
  }
}

export function setAnalyticsOptedOut(optOut: boolean): void {
  try {
    if (optOut) window.localStorage.setItem(OPT_OUT_KEY, "1");
    else window.localStorage.removeItem(OPT_OUT_KEY);
  } catch {
    /* storage unavailable: the account setting still holds */
  }
  if (optOut) tracker.discard();
}

const tracker = createTracker({
  version: APP_VERSION,
  optedOut: () => typeof window === "undefined" || analyticsOptedOut(),
  async send(events) {
    // Loaded on first use: the sign-in library and the API client stay out of every page's first load.
    const [{ getMsal, msalConfigured }, { supportApi }, { demoSession }] = await Promise.all([import("./msal"), import("./billing-api"), import("./demo")]);
    if (!msalConfigured() || demoSession()) return false;
    const msal = await getMsal();
    const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
    return account ? supportApi.sendEvents(account, events) : false;
  },
});

export const track = tracker.track;
export const flushEvents = tracker.flush;

if (typeof window !== "undefined") {
  // A closing tab sends what waits (fetch keepalive); a hidden tab does the same.
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && void tracker.flush());
}
