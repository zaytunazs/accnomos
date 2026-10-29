"use client";

import { useEffect, useState } from "react";

/**
 * Whether this device holds a Microsoft sign-in (hasMsalSignIn below). null until checked on the
 * client, so callers can render nothing rather than flash sample data at someone who is signed in.
 * Re-checked whenever `dep` changes (DemoBanner passes the path).
 */
/**
 * Whether the keys MSAL left in localStorage mean a sign-in. MSAL v5 (5.26) names its account list
 * `msal.3.account.keys` (v2 wrote `msal.account.keys`), its token lists `msal.3.token.keys.<clientId>`, and each
 * account or token entry `msal.3|<homeAccountId>|…`. It also leaves keys that never mean a sign-in: `msal.version`,
 * `msal.<clientId>.active-account-filters`, `msal.browser.*`, and empty lists after a sign-out. Counted as signed in:
 * a non-empty account list, any `msal.N|` entry when there is no list, or this app's own test and demo stand-ins
 * (`msal.accnomos-…`, lib/msal-test.ts and lib/demo.ts).
 *
 * The test used to be "any msal.* key but msal.version", which v5's renamed keys always passed: a device whose MSAL
 * cache could no longer be read (v5 encrypts it with a session cookie) looked signed in while MSAL had no account,
 * and the shell showed neither the menu bar nor the signed-out page (docs/reviews/app-shell/REVIEW.md).
 * SIGNED_IN_PROBE in lib/public-site.ts runs the same test before first paint.
 */
export function hasMsalSignIn(keys: string[], read: (k: string) => string | null): boolean {
  let list: boolean | null = null;
  let entry = false;
  for (const k of keys) {
    if (k.startsWith("msal.accnomos-")) return true;
    if (/^msal\.(\d+\.)?account\.keys$/.test(k)) {
      try {
        const v: unknown = JSON.parse(read(k) ?? "[]");
        list = list || (Array.isArray(v) && v.length > 0);
      } catch {
        list = true;
      }
    } else if (/^msal\.\d+\|/.test(k)) entry = true;
  }
  return list ?? entry;
}

export function useSignedIn(dep?: unknown): boolean | null {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      try {
        const keys: string[] = [];
        for (let i = 0; i < window.localStorage.length; i++) {
          const k = window.localStorage.key(i);
          if (k) keys.push(k);
        }
        setSignedIn(hasMsalSignIn(keys, (k) => window.localStorage.getItem(k)));
      } catch {
        setSignedIn(false);
      }
    });
  }, [dep]);

  return signedIn;
}
