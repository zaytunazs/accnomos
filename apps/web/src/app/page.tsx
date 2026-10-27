import Link from "next/link";
import Activity from "@/components/home/Activity";
import AskBar from "@/components/home/AskBar";
import Deadlines from "@/components/home/Deadlines";
import Greeting from "@/components/home/Greeting";
import { HomeData, SignedOut } from "@/components/home/HomeData";
import InboxTriage from "@/components/home/InboxTriage";
import Pitch from "@/components/home/Pitch";
import PlanToday from "@/components/home/PlanToday";
import Tiles from "@/components/home/Tiles";
import TodosTile from "@/components/home/TodosTile";

export const metadata = { title: "Home · Accnomos" };

export default function HomePage() {
  return (
    <div className="flex flex-col gap-5">
      {/* Greeting, Tiles, Deadlines and Activity share one GET /books/dashboard (the sample when signed out). */}
      <HomeData>
        <SignedOut>
          <Pitch />
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-border bg-white px-4 py-3">
            <p className="text-sm font-semibold text-muted">Not connected yet?</p>
            <Link
              href="/connect"
              className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Connect your OneDrive
            </Link>
          </div>
        </SignedOut>
        <Greeting />
        <AskBar />
        <PlanToday />
        <div className="grid grid-cols-1 items-start gap-3 min-[900px]:grid-cols-[2fr_1fr]">
          <InboxTriage />
          <TodosTile />
        </div>
        <Tiles />
        <Deadlines />
        <Activity />
      </HomeData>
    </div>
  );
}
