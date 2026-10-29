import Link from "next/link";
import Activity from "@/components/home/Activity";
import AskBar from "@/components/home/AskBar";
import Deadlines from "@/components/home/Deadlines";
import HomeError from "@/components/home/HomeError";
import { AttentionCard, TodayCard } from "@/components/home/Tiles";
import { HomeData, SignedOut } from "@/components/home/HomeData";
import InboxTriage from "@/components/home/InboxTriage";
import MonthEndCard from "@/components/home/MonthEndCard";
import { OverviewData } from "@/components/home/Overview";
import {
  AgedCard,
  BuyingCard,
  CisCard,
  ComingUpCard,
  IncomeTaxCard,
  MoneyCard,
  PayrollCard,
  PropertyCard,
  SummaryCard,
} from "@/components/home/OverviewCards";
import { PreviousFilesNotice } from "@/components/files/PreviousFiles";
import Pitch from "@/components/home/Pitch";
import PlanToday from "@/components/home/PlanToday";
import { HomeSampleBooks } from "@/components/home/SampleBooks";
import SetupChecklist from "@/components/home/SetupChecklist";
import SpendingCard from "@/components/home/SpendingCard";
import TodosTile from "@/components/home/TodosTile";

/**
 * Home: signed in, the owner's dashboard (on `/`); signed out, the fictional Bramblewood sample (on `/try`, the
 * landing page's "Try the sample books").
 */
export default function HomeDashboard() {
  return (
    <div className="flex flex-col gap-5">
      {/* Greeting, figures, Deadlines and Activity share one GET /books/dashboard (the sample when signed out). */}
      <HomeData>
        <SignedOut>
          <Pitch />
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-white px-4 py-3">
            <p className="text-sm font-semibold text-muted">Not connected yet?</p>
            <Link
              href="/connect?next=%2Ftry"
              className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Connect your OneDrive
            </Link>
          </div>
        </SignedOut>
        <OverviewData>
          {/* The summary first: two to four sentences on the whole picture, then the detail below. */}
          <SummaryCard />
          <AskBar />
          <HomeError />
          {/* Signed in with an empty folder: offer the sample books; once loaded, the SAMPLE banner. */}
          <HomeSampleBooks />
          <SetupChecklist />
          {/* Signed in: documents already in the OneDrive folders that were never read (asks before reading). */}
          <PreviousFilesNotice />
          {/* One calm grid, signed in or out: 1 column at 390 px, 2 at 768, 3 at 1280. Today spans the row; then
              money, what needs doing and deadlines; then the cards for features these books use (each hides itself
              otherwise: GET /books/home returns null for its section); then buying, to-dos and activity. */}
          <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3">
            <TodayCard />
            <AttentionCard />
            <MoneyCard />
            <ComingUpCard />
            <Deadlines />
            <AgedCard />
            <IncomeTaxCard />
            <PayrollCard />
            <CisCard />
            <PropertyCard />
            <SpendingCard />
            <BuyingCard />
            <TodosTile />
            <MonthEndCard />
            <InboxTriage />
            <PlanToday />
            <Activity />
          </div>
        </OverviewData>
      </HomeData>
    </div>
  );
}
