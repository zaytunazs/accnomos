"use client";

import { useEffect } from "react";
import { getMsal, msalConfigured } from "@/lib/msal";
import { BACKUP_CHECKED_KEY, MONTHLY_BACKUP_KEY, filesApi } from "@/lib/runtime";

/**
 * The optional monthly backup (services/runtime/app/backups.py): there is no server running per user, so the app
 * asks for it when it is opened. Only on a device where the user switched it on (the Files page sets
 * MONTHLY_BACKUP_KEY from the setting saved in their OneDrive), at most once a month per device; the runtime backs
 * up only if no backup is dated this month yet. Renders nothing; a failure is silent and retried next month.
 */
export default function MonthlyBackup() {
  useEffect(() => {
    let month = "";
    try {
      if (window.localStorage.getItem(MONTHLY_BACKUP_KEY) !== "1") return;
      month = new Date().toISOString().slice(0, 7);
      if (window.localStorage.getItem(BACKUP_CHECKED_KEY) === month) return;
    } catch {
      return;
    }
    void (async () => {
      try {
        if (!msalConfigured()) return;
        const msal = await getMsal();
        const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!account) return;
        await filesApi.autoBackup(account);
        window.localStorage.setItem(BACKUP_CHECKED_KEY, month);
      } catch {
        /* next app open tries again */
      }
    })();
  }, []);
  return null;
}
