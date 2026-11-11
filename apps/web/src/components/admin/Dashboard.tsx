"use client";

import AdminFrame, { MiniChart, Stat, card, h2, useLoad, ErrorLine } from "./parts";
import { adminApi } from "@/lib/billing-api";
import { PLAN_NAMES, money, type PlanCode } from "@/lib/billing";

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
  const active = Object.values(m.active_by_plan).reduce((a, b) => a + b, 0);
  const total30 = m.signups.reduce((a, b) => a + b.count, 0);
  return (
    <>
      <div className="grid grid-cols-2 gap-3 min-[900px]:grid-cols-4">
        <Stat label="MRR" value={money(m.mrr_pence)} hint="ex VAT, from active subscriptions" />
        <Stat label="Trialing" value={m.trialing} hint={`${m.trials_ending_7d} ending in 7 days`} />
        <Stat label="Active (paying)" value={active} />
        <Stat label="Past due" value={m.past_due} />
        <Stat label="Cancelled" value={m.cancelled} />
        <Stat label="Sign-ups, 30 days" value={total30} />
        {Object.entries(m.active_by_plan).map(([code, n]) => (
          <Stat key={code} label={`${PLAN_NAMES[code as PlanCode] ?? code} (active)`} value={n} />
        ))}
      </div>
      <section aria-labelledby="signups" className={card}>
        <h2 id="signups" className={h2}>Sign-ups per day, last 30 days</h2>
        <MiniChart data={m.signups} label="Sign-ups per day" />
      </section>
    </>
  );
}
