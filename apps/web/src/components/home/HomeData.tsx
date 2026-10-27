"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { deadlinesQuery, loadBusiness } from "@/lib/business";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, type RtDashboard } from "@/lib/runtime";
import { errorText, todayIso } from "@/components/jobs/useAccount";

/**
 * What Home shows. Signed out: the Bramblewood sample. Signed in: GET /books/dashboard, with skeletons while it loads
 * and "—" for anything unknown (the runtime unreachable, or a section it could not work out). Never the sample.
 */
export type HomeState =
  | { mode: "checking" }
  | { mode: "sample" }
  | { mode: "loading"; account: AccountInfo }
  | { mode: "live"; account: AccountInfo; data: RtDashboard; annualVat: boolean }
  | { mode: "error"; account: AccountInfo; message: string };

const HomeContext = createContext<HomeState>({ mode: "checking" });

export const useHome = () => useContext(HomeContext);

/** "Priya" from the MSAL display name, or the part of the email before the @. */
export function firstName(account: AccountInfo): string {
  const name = (account.name ?? "").trim().split(/\s+/)[0];
  return name || account.username.split("@")[0];
}

export function HomeData({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<HomeState>({ mode: "checking" });

  useEffect(() => {
    (async () => {
      let account: AccountInfo | undefined;
      try {
        if (!msalConfigured()) return setState({ mode: "sample" });
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
      } catch {
        /* MSAL could not start: treat as signed out */
      }
      if (!account) return setState({ mode: "sample" });
      setState({ mode: "loading", account });
      const vat = deadlinesQuery(loadBusiness()); // null for annual returns: the runtime's VAT block is ignored
      try {
        // Today in the UK, not the runtime's time zone (UTC is a day behind just after midnight BST).
        const data = await runtime.dashboard(account, `${vat ? `${vat}&` : ""}today=${todayIso()}`);
        setState({ mode: "live", account, data, annualVat: vat === null });
      } catch (e) {
        setState({ mode: "error", account, message: errorText(e) });
      }
    })();
  }, []);

  return <HomeContext.Provider value={state}>{children}</HomeContext.Provider>;
}

/** Only for visitors who are not signed in (and in the static HTML, before MSAL has answered). */
export function SignedOut({ children }: { children: React.ReactNode }) {
  const { mode } = useHome();
  return mode === "checking" || mode === "sample" ? <>{children}</> : null;
}

/** A grey bar standing in for text that is still loading. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`inline-block animate-pulse rounded-md bg-ground ${className}`} />;
}

/** Small "Sample" pill flagging a card that shows the fictional Bramblewood books (signed out). */
export function SampleTag() {
  return (
    <span className="ml-2 rounded-full bg-ground px-2 py-0.5 align-middle text-[11px] font-extrabold uppercase tracking-wide text-muted">
      Sample
    </span>
  );
}

export const UNKNOWN = "—";

/** "£12,480" from pence (whole pounds, as the tiles show them); "—" when unknown. */
export function pounds(p: number | null | undefined): string {
  if (p === null || p === undefined) return UNKNOWN;
  return `${p < 0 ? "-" : ""}£${Math.round(Math.abs(p) / 100).toLocaleString("en-GB")}`;
}

/** "24 Oct" from "2026-10-24", without a time zone. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const [, m, d] = iso.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${months[m - 1] ?? ""}`;
}
