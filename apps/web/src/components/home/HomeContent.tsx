"use client";

import Link from "next/link";
import { useAccount } from "@/components/jobs/useAccount";
import { LoadingSkeleton } from "@/components/States";
import Activity from "@/components/home/Activity";
import AskBar from "@/components/home/AskBar";
import DashboardGrid from "@/components/home/DashboardGrid";
import Deadlines from "@/components/home/Deadlines";
import LastInboxCheck from "@/components/home/LastInboxCheck";
import PlanToday from "@/components/home/PlanToday";
import Tiles from "@/components/home/Tiles";
import Pitch from "@/components/home/Pitch";

/** The banner every signed-out visitor sees, above the sample cards. */
function ConnectBanner() {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-white px-4 py-3">
      <p className="text-sm font-semibold text-muted">Not connected yet?</p>
      <Link
        href="/connect"
        className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
      >
        Connect your OneDrive
      </Link>
    </div>
  );
}

function Greeting() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <p className="text-sm font-semibold text-muted">Monday 26 October</p>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">
          Good evening, Priya
        </h1>
      </div>
      <LastInboxCheck>Last Autopilot run 4 min ago · 2 receipts imported from Outlook</LastInboxCheck>
    </div>
  );
}

/**
 * Home below the pitch. Signed out: the connect banner and the sample cards.
 * Signed in: the greeting, Ask, the day planner and one uniform dashboard grid.
 */
export default function HomeContent() {
  const account = useAccount();

  if (account === undefined) {
    return (
      <div className="flex flex-col gap-5">
        <Pitch />
        <LoadingSkeleton lines={3} label="Checking your sign-in…" />
      </div>
    );
  }

  if (account === null) {
    return (
      <div className="flex flex-col gap-5">
        <Pitch />
        <ConnectBanner />
        <Tiles />
        <Deadlines />
        <Activity />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Pitch />
      <Greeting />
      <AskBar />
      <PlanToday />
      <DashboardGrid />
      <Deadlines />
      <Activity />
    </div>
  );
}
