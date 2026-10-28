"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import Explain from "@/components/Explain";
import { RuntimeErrorNote } from "@/components/States";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import { runtime, type RtCloseOverview } from "@/lib/runtime";

/**
 * Home › Month-end: "October: 3 things need you before close", from GET /close (the last run's counts, read from
 * _System/close; nothing is recomputed here), or "October was closed on 3 Nov; 2 changes since … — re-close?".
 */
export default function MonthEndCard() {
  const account = useAccount();
  const [data, setData] = useState<RtCloseOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!account) return;
    runtime.closeOverview(account, todayIso()).then(setData, (e) => setError(errorText(e)));
  }, [account]);

  const target = data?.target;
  const changed = data?.changed ?? [];
  const warn = !!target?.changes || changed.length > 0;
  const month = target?.month;

  return (
    <section
      aria-labelledby="home-month-end"
      className={`flex flex-col rounded-2xl border bg-white p-4 sm:p-5 ${warn ? "border-warn-border" : "border-border"}`}
    >
      <div className="flex items-center gap-2">
        <h2 id="home-month-end" className="text-lg font-extrabold tracking-tight">
          Month-end
        </h2>
        <Explain title="The month-end close">
          <p>
            Close a month in one go: code checks the inbox, bank, sales, purchases, payroll, VAT and the month&apos;s
            figures, and turns what needs you into cards. Nothing is posted until you approve. If anything dated in a
            closed month changes later, this card says so.
          </p>
        </Explain>
      </div>
      <p className={`mt-1 min-h-[3.5rem] text-[15px] leading-6 ${warn ? "font-semibold text-warn-ink" : "text-ink"}`}>
        {account === null
          ? "Sign in to close a month: one button works through the checklist."
          : target
            ? target.headline
            : error
              ? ""
              : "Checking…"}
      </p>
      {changed.map((c) => (
        <p key={c.month} className="text-[14px] font-semibold text-warn-ink">
          <Link href={`/month-end?month=${c.month}`} className="underline">
            {c.headline}
          </Link>
        </p>
      ))}
      {error && <RuntimeErrorNote message={error} />}
      <ByWhom className="mt-2" code="Checks and figures by code" ai="nothing posted without your OK" />
      <div className="mt-auto pt-4">
        <Link
          href={month ? `/month-end?month=${month}` : "/month-end"}
          className="inline-flex shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
        >
          {target?.changes ? "Review and re-close" : "Open Month-end"}
        </Link>
      </div>
    </section>
  );
}
