"use client";

import { useEffect, useState } from "react";

/**
 * Whether this device holds a Microsoft sign-in (any `msal.` key in localStorage). null until checked on the
 * client, so callers can render nothing rather than flash sample data at someone who is signed in.
 * Re-checked whenever `dep` changes (DemoBanner passes the path).
 */
/**
 * MSAL writes `msal.version` the moment it initialises, and leaves empty `msal.account.keys` / `msal.token.keys.*`
 * lists behind after a sign-out — none of those mean a sign-in. Only account or token entries do.
 */
export function hasMsalSignIn(keys: string[], read: (k: string) => string | null): boolean {
  for (const k of keys) {
    if (!k.startsWith("msal.") || k === "msal.version") continue;
    if (k === "msal.account.keys" || k.startsWith("msal.token.keys")) {
      try {
        const list: unknown = JSON.parse(read(k) ?? "[]");
        if (Array.isArray(list) && list.length > 0) return true;
      } catch {
        return true;
      }
      continue;
    }
    return true;
  }
  return false;
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
