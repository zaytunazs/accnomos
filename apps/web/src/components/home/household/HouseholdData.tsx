"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { errorText, todayIso } from "@/components/jobs/useAccount";
import { currentMeta, PROFILE_EVENT } from "@/lib/profiles";
import { monthBefore, monthOf } from "@/lib/personal";
import { runtime, type RtPersonalRecurring, type RtPersonalSummary, type RtProfileKind } from "@/lib/runtime";
import { useHome } from "../HomeData";
import { useOverviewData } from "../Overview";

/**
 * Whether Home is a household's (a personal profile): GET /books/home says so once loaded; before that, the profile
 * last read on this device (lib/profiles.ts), so a household never flashes the business layout. Signed out (the
 * Bramblewood sample) and while checking: never.
 */
export function useIsHousehold(): boolean {
  const home = useHome();
  const overview = useOverviewData();
  const [kind, setKind] = useState<RtProfileKind | undefined>(undefined);
  useEffect(() => {
    const read = () => setKind(currentMeta()?.kind);
    queueMicrotask(read);
    window.addEventListener(PROFILE_EVENT, read);
    return () => window.removeEventListener(PROFILE_EVENT, read);
  }, []);
  if (home.mode === "sample" || home.mode === "checking") return false;
  if (overview) return overview.kind === "personal";
  return kind === "personal";
}

/** Home's layout by the kind of books: the household one for personal books, the business one otherwise. */
export function HomeByKind({ business, household }: { business: React.ReactNode; household: React.ReactNode }) {
  return <>{useIsHousehold() ? household : business}</>;
}

export type HouseholdState =
  | { mode: "loading" }
  | { mode: "live"; month: string; thisMonth: RtPersonalSummary; lastMonth: RtPersonalSummary; recurring: RtPersonalRecurring }
  | { mode: "error"; message: string };

const HouseholdContext = createContext<{ state: HouseholdState; reload: () => void }>({
  state: { mode: "loading" },
  reload: () => {},
});

export const useHousehold = () => useContext(HouseholdContext);

/**
 * The household's month for Home: GET /personal/summary for this month and last, and GET /personal/recurring
 * (services/runtime/app/routes_personal.py). Every figure is worked out by the runtime; nothing here adds up money.
 */
export function HouseholdData({ children }: { children: React.ReactNode }) {
  const home = useHome();
  const account = home.mode === "loading" || home.mode === "live" || home.mode === "error" ? home.account : null;
  const [state, setState] = useState<HouseholdState>({ mode: "loading" });

  const load = useCallback(async () => {
    if (!account) return;
    const month = monthOf(todayIso());
    try {
      const [thisMonth, lastMonth, recurring] = await Promise.all([
        runtime.personal.summary(account, month),
        runtime.personal.summary(account, monthBefore(month)),
        runtime.personal.recurring(account),
      ]);
      setState({ mode: "live", month, thisMonth, lastMonth, recurring });
    } catch (e) {
      setState({ mode: "error", message: errorText(e) ?? "Could not read your household figures" });
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  return <HouseholdContext.Provider value={{ state, reload: () => void load() }}>{children}</HouseholdContext.Provider>;
}

/** Whether any bank statement has been imported: a month with no lines this month or last, and no regular bills. */
export function hasStatements(s: Extract<HouseholdState, { mode: "live" }>): boolean {
  return s.thisMonth.lines + s.lastMonth.lines > 0 || s.recurring.items.length > 0;
}
