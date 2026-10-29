"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  launchBadgeText,
  loadLastLaunchCheck,
  saveLastLaunchCheck,
  shouldRunLaunchCheck,
  type RtLaunchCheck,
} from "@/lib/bulk";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime } from "@/lib/runtime";

/**
 * The launch check: after first paint, compare 01 Bulk upload and 00 Inbox with
 * what the books already know (lists only, no downloads). A thin progress bar
 * sits at the very top of the page while it runs, then a small badge
 * ("N new, M changed - Review"). Never blocks rendering or navigation; the
 * request is cancelled on sign-out (unmount), and throttled to once per
 * 10 minutes per tab.
 */
export default function LaunchCheckBar() {
  const [checking, setChecking] = useState(false);
  const [found, setFound] = useState<RtLaunchCheck | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    let idle: number | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    const run = async () => {
      if (cancelled || !msalConfigured()) return;
      let account = null;
      try {
        const msal = await getMsal();
        account = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
      } catch {
        return;
      }
      if (cancelled || !account) return;
      if (!shouldRunLaunchCheck(loadLastLaunchCheck(), Date.now())) return;
      abort.current = new AbortController();
      setChecking(true);
      try {
        const result = await runtime.launchCheck(account, abort.current.signal);
        if (cancelled) return;
        saveLastLaunchCheck(Date.now());
        if (result.new.length > 0 || result.changed.length > 0) setFound(result);
      } catch {
        /* aborted on sign-out, offline, or a failed check: stay quiet */
      } finally {
        if (!cancelled) setChecking(false);
      }
    };
    if (typeof window.requestIdleCallback === "function") {
      idle = window.requestIdleCallback(() => void run(), { timeout: 2000 });
    } else {
      timer = setTimeout(() => void run(), 0);
    }
    return () => {
      cancelled = true;
      if (idle !== null) window.cancelIdleCallback(idle);
      if (timer !== null) clearTimeout(timer);
      abort.current?.abort();
    };
  }, []);

  return (
    <div aria-live="polite" className="w-full">
      {checking && (
        <div
          role="progressbar"
          aria-label="Checking for new files"
          className="h-1 w-full overflow-hidden bg-teal-tint"
        >
          <div className="h-full w-1/3 animate-[launchslide_1.2s_ease-in-out_infinite] rounded-r bg-teal" />
        </div>
      )}
      {found && !checking && (
        <div className="flex w-full justify-center border-b border-border bg-white px-4 py-1.5">
          <Link href="/review" className="text-sm font-bold text-teal-dark underline underline-offset-2">
            {launchBadgeText(found)}
          </Link>
        </div>
      )}
      <style>{`@keyframes launchslide { 0% { margin-left: -33%; } 100% { margin-left: 100%; } }`}</style>
    </div>
  );
}
