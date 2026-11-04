import Link from "next/link";
import Activity from "@/components/home/Activity";
import AskBar from "@/components/home/AskBar";
import Deadlines from "@/components/home/Deadlines";
import HomeError from "@/components/home/HomeError";
import { AttentionTiles, TodayCard } from "@/components/home/Tiles";
import { HomeData, SignedOut } from "@/components/home/HomeData";
import HomeGoals from "@/components/home/HomeGoals";
import { HomeByKind, HouseholdData } from "@/components/home/household/HouseholdData";
import { Bills, Budgets, HouseholdTiles, ThisMonth, WhereItWent } from "@/components/home/household/HouseholdPanels";
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
import { SnapshotCharts, SnapshotYear } from "@/components/home/Snapshot";
import SpendingCard from "@/components/home/SpendingCard";
import TodosTile from "@/components/home/TodosTile";

/**
 * Home: signed in, the owner's dashboard (on `/`); signed out, the fictional Bramblewood sample (on `/try`, the
 * landing page's "Try the sample books").
 */
export default function HomeDashboard() {
  return (
    <div className="flex flex-col gap-6">
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
          <HomeByKind
            business={
              <>
              {/* The order, top to bottom: which books these are and anything wrong (the sample banner, an error);
                  the summary, the ask bar under it, and what needs attention; the compact year to date; Goals &
                  progress with its note; the monthly and cash charts; then the secondary cards and activity. */}
              {/* Signed in with an empty folder: offer the sample books; once loaded, the SAMPLE banner. */}
              <HomeSampleBooks />
              <HomeError />
              {/* The summary: two to four sentences on the whole picture, then the detail below. */}
              <SummaryCard />
              <AskBar />
              {/* What needs attention, one tap from Review, Invoices and Bank (up to four tiles, 2 by 2 on a phone). */}
              <AttentionTiles />
              {/* The business snapshot's year to date against last year (GET /books/home snapshot); personal books: nothing. */}
              <SnapshotYear />
              {/* Goals & progress: up to three goals, most urgent first, and the checked note (GET /books/goals). */}
              <HomeGoals />
              {/* The last 12 months and the 90-day cash line (the same GET /books/home: trend, cash_points). */}
              <SnapshotCharts />
              <SetupChecklist />
              {/* Signed in: documents already in the OneDrive folders that were never read (asks before reading). */}
              <PreviousFilesNotice />
              {/* One calm grid, signed in or out: 1 column at 390 px, 2 at 768, 3 at 1280. Today spans the row; then
                  money, deadlines and who owes what; then spending, buying, to-dos and month-end; then the cards for
                  features these books use (each hides itself otherwise: GET /books/home returns null for its section);
                  then the inbox, the day's plan and activity. */}
              <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
                <TodayCard />
                <MoneyCard />
                <ComingUpCard />
                <Deadlines />
                <AgedCard />
                <SpendingCard />
                <BuyingCard />
                <TodosTile />
                <MonthEndCard />
                <IncomeTaxCard />
                <PayrollCard />
                <CisCard />
                <PropertyCard />
                <InboxTriage />
                <PlanToday />
                <Activity />
              </div>
              </>
            }
            household={
              /* A household (personal books): no turnover, VAT or invoices. Its month, budgets, goals and regular bills,
                 all worked out by code from the imported statements (GET /personal/summary, /personal/recurring). */
              <HouseholdData>
                {/* The same order as a business: anything wrong, the summary and what needs attention, the month so
                    far, Goals & progress with its note, then budgets, bills, where the money went and the rest. */}
                <HomeError />
                <SummaryCard />
                <AskBar example="where did my money go this month?" />
                <HouseholdTiles />
                <ThisMonth />
                <HomeGoals />
                <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
                  <Budgets />
                  <Bills />
                </div>
                <WhereItWent />
                {/* A household that lets property or is self-employed still has Income Tax: these hide themselves
                    otherwise (GET /books/home returns null for their sections). */}
                <div className="grid grid-cols-1 items-stretch gap-4 empty:hidden md:grid-cols-2">
                  <PropertyCard />
                  <IncomeTaxCard />
                </div>
                <SetupChecklist />
                <PreviousFilesNotice />
                <Activity />
              </HouseholdData>
            }
          />
        </OverviewData>
      </HomeData>
    </div>
  );
}
