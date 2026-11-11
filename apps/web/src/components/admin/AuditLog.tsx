"use client";

import { useState } from "react";
import AdminFrame, { ErrorLine, card, input, td, th, useLoad } from "./parts";
import { adminApi } from "@/lib/billing-api";
import { longDate } from "@/lib/billing";

export default function AuditLog() {
  return (
    <AdminFrame title="Audit log" description="Every admin change: who, when, and what.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

function Body({ account }: { account: Parameters<typeof adminApi.audit>[0] }) {
  const [id, setId] = useState("");
  const { data, error } = useLoad(() => adminApi.audit(account, { account_id: id.trim() || undefined }), [account, id]);
  return (
    <section className={card} aria-label="Audit">
      <input aria-label="Filter by account id" placeholder="Filter by account id" className={`${input} w-full max-w-sm`} value={id} onChange={(e) => setId(e.target.value)} />
      <ErrorLine error={error} />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem]">
          <thead><tr className="border-b border-border"><th className={th}>When</th><th className={th}>Admin</th><th className={th}>Account</th><th className={th}>Action</th><th className={th}>Detail</th></tr></thead>
          <tbody>
            {data?.map((r) => <tr key={r.id} className="border-b border-border last:border-0"><td className={td}>{longDate(r.at)}</td><td className={td}>{r.admin_email}</td><td className={td}>{r.account_id ?? "—"}</td><td className={`${td} font-bold`}>{r.action}</td><td className={`${td} text-muted`}>{JSON.stringify(r.detail)}</td></tr>)}
            {data && data.length === 0 && <tr><td className={td} colSpan={5}>Nothing recorded.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
