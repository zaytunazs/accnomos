"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";

const KEY = "accnomos.admin.checked";

/**
 * Whether this account is an administrator: GET /admin/metrics succeeds (the runtime checks ADMIN_EMAILS server-side).
 * Asked once per browser session per account; the menu shows the Admin link only on true. Never decides access: the
 * runtime refuses every admin call from anyone else.
 */
export function useIsAdmin(account: AccountInfo | null | undefined): boolean {
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    if (!account) return;
    let live = true;
    const k = `${KEY}.${account.homeAccountId}`;
    try {
      const seen = window.sessionStorage.getItem(k);
      if (seen !== null) {
        queueMicrotask(() => live && setAdmin(seen === "1"));
        return () => {
          live = false;
        };
      }
    } catch {
      /* no session storage: ask each time */
    }
    import("./billing-api")
      .then((m) => m.adminApi.metrics(account))
      .then(
        () => true,
        () => false,
      )
      .then((ok) => {
        try {
          window.sessionStorage.setItem(k, ok ? "1" : "0");
        } catch {
          /* ignore */
        }
        if (live) setAdmin(ok);
      });
    return () => {
      live = false;
    };
  }, [account]);
  return admin;
}
