"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";

/** The signed-in Microsoft account: undefined while checking, null when signed out. */
export function useAccount(): AccountInfo | null | undefined {
  const [account, setAccount] = useState<AccountInfo | null | undefined>(undefined);
  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setAccount(null);
        const msal = await getMsal();
        setAccount(msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null);
      } catch {
        setAccount(null);
      }
    })();
  }, []);
  return account;
}

export const errorText = (e: unknown) => {
  const m = (e as Error).message ?? String(e);
  const detail = /"detail":\s*"([^"]+)"/.exec(m);
  return detail ? detail[1] : m;
};

export const todayIso = () => new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
