"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ErrorLine, card, h2, input, td, th, useLoad } from "./parts";
import { fieldLabel, primaryButton } from "@/components/invoices/Modal";
import { adminApi } from "@/lib/billing-api";
import { BUG_LABEL, BUG_STATUSES, type BugReport, type BugStatus } from "@/lib/admin";
import { longDate } from "@/lib/billing";

export default function BugReports() {
  return (
    <AdminFrame title="Bug reports" description="What users have reported from the web and Android apps.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

function Body({ account }: { account: AccountInfo }) {
  const [status, setStatus] = useState<"" | BugStatus>("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    queueMicrotask(() => setOpen(new URLSearchParams(window.location.search).get("id")));
  }, []);
  const { data, error, reload } = useLoad(() => adminApi.bugs(account, { status }), [account, status]);
  // The report stays open after it is saved, even when the new status takes it out of the filtered list.
  const [kept, setKept] = useState<BugReport | null>(null);
  const chosen = kept?.id === open ? kept : (data?.find((b) => b.id === open) ?? null);
  return (
    <>
      <div role="tablist" aria-label="Status" className="flex flex-wrap gap-2">
        {(["", ...BUG_STATUSES] as const).map((s) => (
          <button key={s || "all"} type="button" role="tab" aria-selected={status === s} onClick={() => setStatus(s)} className={`h-10 rounded-xl border px-3 text-sm font-bold ${status === s ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border bg-white"}`}>
            {s ? BUG_LABEL[s] : "All"}
          </button>
        ))}
      </div>
      <ErrorLine error={error} />
      <section className={card} aria-label="Reports">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem]" data-bugs-table="">
            <thead><tr className="border-b border-border"><th className={th}>When</th><th className={th}>Message</th><th className={th}>Page</th><th className={th}>App</th><th className={th}>Status</th></tr></thead>
            <tbody>
              {data?.map((b) => (
                <tr key={b.id} className="border-b border-border last:border-0 hover:bg-ground">
                  <td className={td}>{longDate(b.at)}</td>
                  <td className={td}><button type="button" className="text-left font-bold text-teal-dark underline underline-offset-2" onClick={() => setOpen(b.id)}>{b.message.slice(0, 80)}</button></td>
                  <td className={td}>{b.page}</td><td className={td}>{b.app} {b.version}</td><td className={td}>{BUG_LABEL[b.status]}</td>
                </tr>
              ))}
              {data && data.length === 0 && <tr><td className={td} colSpan={5}>No reports.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {chosen && <Detail key={chosen.id} bug={chosen} account={account} onSaved={(b) => { setKept(b); reload(); }} />}
    </>
  );
}

function Detail({ bug, account, onSaved }: { bug: BugReport; account: AccountInfo; onSaved: (b: BugReport) => void }) {
  const [status, setStatus] = useState<BugStatus>(bug.status);
  const [notes, setNotes] = useState(bug.admin_notes);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shot = bug.screenshot_b64 ? `data:image/png;base64,${bug.screenshot_b64}` : null;
  return (
    <section className={card} aria-labelledby="bug-detail">
      <h2 id="bug-detail" className={h2}>Report from {bug.email ?? "unknown"}</h2>
      <p className="mt-2 whitespace-pre-wrap text-[15px]">{bug.message}</p>
      <dl className="mt-3 grid gap-1 text-sm min-[700px]:grid-cols-2">
        <div><dt className="inline font-bold">Page: </dt><dd className="inline">{bug.page}</dd></div>
        <div><dt className="inline font-bold">App: </dt><dd className="inline">{bug.app} {bug.version}</dd></div>
        <div className="min-[700px]:col-span-2"><dt className="inline font-bold">Browser / phone: </dt><dd className="inline">{bug.ua}</dd></div>
      </dl>
      <div className="mt-3">
        <p className={fieldLabel}>Screenshot</p>
        {shot ? (
          // eslint-disable-next-line @next/next/no-img-element -- a data URL, which next/image cannot optimise
          <img src={shot} alt="Screenshot sent with the report" className="mt-1 max-h-96 rounded-xl border border-border" />
        ) : (<p className="text-sm text-muted">{bug.screenshot_path ? `Stored at ${bug.screenshot_path}` : "None attached."}</p>
        )}
      </div>
      <div className="mt-3 grid gap-3 min-[700px]:grid-cols-[12rem_1fr]">
        <label><span className={fieldLabel}>Status</span><select className={`${input} w-full`} value={status} onChange={(e) => setStatus(e.target.value as BugStatus)}>{BUG_STATUSES.map((s) => <option key={s} value={s}>{BUG_LABEL[s]}</option>)}</select></label>
        <label><span className={fieldLabel}>Notes</span><textarea className="mt-1 w-full rounded-xl border border-border p-2 text-sm" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      <ErrorLine error={error} />
      <button type="button" className={`${primaryButton} mt-3`} onClick={async () => { try { const updated = await adminApi.patchBug(account, bug.id, { status, admin_notes: notes }); setSaved(true); setError(null); onSaved({ ...bug, ...updated }); } catch (e) { setError((e as Error).message); } }}>Save</button>
      {saved && <span role="status" className="ml-3 text-sm font-bold text-teal-dark">Saved.</span>}
    </section>
  );
}
