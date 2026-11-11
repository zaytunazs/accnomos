"use client";

import Link from "next/link";
import { useState } from "react";
import AdminFrame, { ErrorLine, card, input, td, th, useLoad } from "./parts";
import { adminApi } from "@/lib/billing-api";
import { PLAN_CODES, PLAN_NAMES, STATUS_LABEL, longDate, type BillingStatus } from "@/lib/billing";

export default function UsersList() {
  return (
    <AdminFrame title="Users" description="Search accounts, then open one to change its plan or help.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

function Body({ account }: { account: Parameters<typeof adminApi.users>[0] }) {
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, error } = useLoad(() => adminApi.users(account, { q, plan, status, page }), [account, q, plan, status, page]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <section className={card} aria-label="Users">
      <div className="flex flex-wrap gap-2">
        <input aria-label="Search by email or name" placeholder="Search email or name" className={`${input} min-w-0 flex-1`} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select aria-label="Plan" className={input} value={plan} onChange={(e) => { setPlan(e.target.value); setPage(1); }}>
          <option value="">All plans</option>
          {PLAN_CODES.map((c) => <option key={c} value={c}>{PLAN_NAMES[c]}</option>)}
        </select>
        <select aria-label="Status" className={input} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {(Object.keys(STATUS_LABEL) as BillingStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
      </div>
      <ErrorLine error={error} />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse" data-users-table="">
          <thead>
            <tr className="border-b border-border">
              <th className={th}>Account</th><th className={th}>Plan</th><th className={th}>Status</th><th className={th}>Signed up</th><th className={th}>Last seen</th><th className={th}>Docs</th><th className={th}>Ask</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((u) => (
              <tr key={u.id} className="border-b border-border last:border-0 hover:bg-ground">
                <td className={td}>
                  <Link href={`/admin/user?id=${encodeURIComponent(u.id)}`} className="font-bold text-teal-dark underline underline-offset-2">{u.email}</Link>
                  {u.display_name && <span className="block text-xs text-muted">{u.display_name}</span>}
                </td>
                <td className={td}>{PLAN_NAMES[u.plan_code] ?? u.plan_code}</td>
                <td className={td}>{STATUS_LABEL[u.status] ?? u.status}</td>
                <td className={td}>{longDate(u.created_at)}</td>
                <td className={td}>{longDate(u.last_seen_at)}</td>
                <td className={td}>{u.usage.docs}</td>
                <td className={td}>{u.usage.ask}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td className={td} colSpan={7}>No accounts match.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-2 text-sm">
        <button type="button" className="h-10 rounded-xl border border-border px-3 font-bold disabled:opacity-50" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span>Page {page} of {pages}{data ? ` · ${data.total} accounts` : ""}</span>
        <button type="button" className="h-10 rounded-xl border border-border px-3 font-bold disabled:opacity-50" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </section>
  );
}
