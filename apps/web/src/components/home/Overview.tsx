"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { deadlinesQuery, loadBusiness } from "@/lib/business";
import { runtime, type RtHome } from "@/lib/runtime";
import { sampleOverview } from "@/lib/sample-home";
import { errorText, todayIso } from "@/components/jobs/useAccount";
import { useHome } from "./HomeData";

/**
 * Home's other cards and the summary: one GET /books/home (services/runtime/app/home_overview.py), fetched once the
 * signed-in account is known. Signed out (on /try): the fictional Bramblewood sample. Cards whose section is null
 * (a feature these books do not use) render nothing.
 */
export type OverviewState =
  | { mode: "waiting" }
  | { mode: "sample"; data: RtHome }
  | { mode: "live"; data: RtHome; wording?: boolean }
  | { mode: "error"; message: string };

const OverviewContext = createContext<OverviewState>({ mode: "waiting" });

export const useOverview = () => useContext(OverviewContext);

/** The data, live or sample; null while loading or after an error. */
export function useOverviewData(): RtHome | null {
  const o = useOverview();
  return o.mode === "live" || o.mode === "sample" ? o.data : null;
}

export function OverviewData({ children }: { children: React.ReactNode }) {
  const home = useHome();
  const [state, setState] = useState<OverviewState>({ mode: "waiting" });
  const account = home.mode === "loading" || home.mode === "live" || home.mode === "error" ? home.account : null;
  const sample = home.mode === "sample";

  useEffect(() => {
    if (sample) {
      queueMicrotask(() => setState({ mode: "sample", data: sampleOverview }));
      return;
    }
    if (!account) return;
    let stale = false;
    const business = loadBusiness();
    const vat = business ? deadlinesQuery(business) : "";
    const query = `${vat ? `${vat}&` : ""}today=${todayIso()}`;
    // Two steps, so Home never waits on the model: every card from a fast call whose summary code writes, then the
    // same call with the AI wording it, swapped in when (if) it arrives. A failure there keeps code's summary.
    runtime.home(account, `${query}&summary_ai=false`).then(
      (data) => {
        if (stale) return;
        setState({ mode: "live", data, wording: true });
        runtime.home(account, `${query}&summary_ai=true`).then(
          (full) => !stale && setState({ mode: "live", data: { ...data, summary: full.summary } }),
          () => !stale && setState({ mode: "live", data }),
        );
      },
      (e) => !stale && (e as Error).message !== "redirecting for consent" && setState({ mode: "error", message: errorText(e) }),
    );
    return () => {
      stale = true;
    };
  }, [account, sample]);

  return <OverviewContext.Provider value={state}>{children}</OverviewContext.Provider>;
}
