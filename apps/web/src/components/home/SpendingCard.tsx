"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ByWhom from "@/components/ByWhom";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import { runtime, type RtSpending } from "@/lib/runtime";
import { change, money } from "@/lib/spending";

/** Home › Spending: this month's spend before VAT against last month, and the checked summary's first lines. */
export default function SpendingCard() {
  const account = useAccount();
  const [data, setData] = useState<RtSpending | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!account) return;
    let stale = false;
    runtime.spending(account).then(
      (d) => !stale && setData(d),
      (e) => !stale && (e as Error).message !== "redirecting for consent" && setError(errorText(e)),
    );
    return () => {
      stale = true;
    };
  }, [account]);

  const t = data?.facts.this_period;
  return (
    <section aria-labelledby="home-spending" className="flex flex-col rounded-2xl border border-border bg-white p-4 sm:p-5">
      <h2 id="home-spending" className="text-lg font-extrabold tracking-tight">
        Spending
      </h2>
      <p className="mt-1 min-h-9 text-3xl font-extrabold tracking-tight tabular-nums text-ink">{t ? money(t.spent) : "–"}</p>
      <p className="min-h-5 text-[13px] font-semibold text-muted">
        {account === null
          ? "Sign in to see where your money goes"
          : t && data
            ? `${t.label}, before VAT · ${change(data.facts.change.spent_vs_previous)} on ${data.facts.previous_period.label}`
            : "This month, before VAT"}
      </p>
      {error && <RuntimeErrorNote message={error} />}
      <p className="mt-3 min-h-[3.5rem] text-sm leading-6 text-ink">{data?.summary_md ?? ""}</p>
      <ByWhom className="mt-2" code="Figures by code from your approved purchases" ai="summary by your AI, checked" />
      {account ? (
        <div className="mt-auto pt-4">
          <Link href="/spending" className="inline-block whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark">
            Open spending
          </Link>
        </div>
      ) : null}
    </section>
  );
}
