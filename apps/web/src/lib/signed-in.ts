"use client";

import { useEffect, useState } from "react";

/**
 * Whether this device holds a Microsoft sign-in (any `msal.` key in localStorage). null until checked on the
 * client, so callers can render nothing rather than flash sample data at someone who is signed in.
 * Re-checked whenever `dep` changes (DemoBanner passes the path).
 */
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
        setSignedIn(keys.some((k) => k.startsWith("msal.")));
      } catch {
        setSignedIn(false);
      }
    });
  }, [dep]);

  return signedIn;
}
