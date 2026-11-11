"use client";

import AdminFrame, { MiniChart, Stat, card, h2, useLoad, ErrorLine } from "./parts";
import { adminApi } from "@/lib/billing-api";
import Link from "next/link";
import { PLAN_NAMES, longDate, money, type PlanCode } from "@/lib/billing";

export default function Dashboard() {
  return (
    <AdminFrame title="Admin" description="Accounts, revenue and how the product is used.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

function Body({ account }: { account: Parameters<typeof adminApi.metrics>[0] }) {
  const { data: m, error } = useLoad(() => adminApi.metrics(account), [account]);
  if (error) return <ErrorLine error={error} />;
  if (!m) return <p className="text-sm text-muted">Loading…</p>;
  const total30 = m.signups_by_day.reduce((a, b) => a + b.count, 0);
  return (
    <>
      <div className="grid grid-cols-2 gap-3 min-[900px]:grid-cols-4">
        <Stat label="MRR" value={money(m.mrr_pence)} hint="ex VAT, from active subscriptions" />
        <Stat label="Trialing" value={m.trialing} hint={`${m.trials_ending_7d} ending in 7 days`} />
        <Stat label="Active (paying)" value={m.active} />
        <Stat label="Past due" value={m.past_due} />
        <Stat label="Cancelled" value={m.cancelled} />
        <Stat label="Trial ended" value={m.trial_ended} hint="read-only until they choose a plan" />
        <Stat label="Free access" value={m.comped} />
        <Stat label="All accounts" value={m.total_accounts} />
        <Stat label="Sign-ups, 30 days" value={total30} />
        {Object.entries(m.active_by_plan).map(([code, n]) => (
          <Stat key={code} label={`${PLAN_NAMES[code as PlanCode] ?? code} (active)`} value={n} />
        ))}
      </div>
      <section aria-labelledby="signups" className={card}>
        <h2 id="signups" className={h2}>Sign-ups per day, last 30 days</h2>
        <MiniChart data={m.signups_by_day} label="Sign-ups per day" />
      </section>
      {m.trials_ending.length > 0 && (
        <section aria-labelledby="trials-ending" className={card}>
          <h2 id="trials-ending" className={h2}>Trials ending in the next 7 days</h2>
          <ul className="mt-2 text-sm">
            {m.trials_ending.map((t) => (
              <li key={t.id} className="flex justify-between gap-3 border-t border-border py-1.5 first:border-0">
                <Link href={`/admin/user?id=${encodeURIComponent(t.id)}`} className="font-bold text-teal-dark underline underline-offset-2">{t.email}</Link>
                <span>{longDate(t.trial_ends_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
