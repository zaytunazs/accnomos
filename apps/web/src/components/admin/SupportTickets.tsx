"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import AdminFrame, { ErrorLine, card, h2, input, td, th, useLoad } from "./parts";
import { fieldLabel, primaryButton } from "@/components/invoices/Modal";
import { longDate } from "@/lib/billing";
import { ADMIN_STATUS_LABEL, categoryLabel, supportDesk, type TicketStatus, type TicketThread } from "@/lib/support-api";

const STATUSES: TicketStatus[] = ["open", "pending", "solved"];

export default function SupportTickets() {
  return (
    <AdminFrame title="Support tickets" description="Tickets from the Support page and the assistant. Reply, add an internal note, or change the status.">
      {(account) => <Body account={account} />}
    </AdminFrame>
  );
}

function Body({ account }: { account: AccountInfo }) {
  const [status, setStatus] = useState<"" | TicketStatus>("open");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    queueMicrotask(() => setOpen(new URLSearchParams(window.location.search).get("id")));
  }, []);
  const { data, error, reload } = useLoad(() => supportDesk.admin.list(account, { status, q, page }), [account, status, q, page]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <div role="tablist" aria-label="Status" className="flex flex-wrap gap-2">
          {(["", ...STATUSES] as const).map((s) => (
            <button key={s || "all"} type="button" role="tab" aria-selected={status === s} onClick={() => { setStatus(s); setPage(1); }} className={`h-10 rounded-xl border px-3 text-sm font-bold ${status === s ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border bg-white"}`}>
              {s ? `${ADMIN_STATUS_LABEL[s]}${data ? ` (${data.counts[s]})` : ""}` : "All"}
            </button>
          ))}
        </div>
        <label className="ml-auto"><span className="sr-only">Search</span><input className={input} placeholder="Subject or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></label>
      </div>
      <ErrorLine error={error} />
      <section className={card} aria-label="Tickets">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem]">
            <thead><tr className="border-b border-border"><th className={th}>#</th><th className={th}>Subject</th><th className={th}>From</th><th className={th}>Category</th><th className={th}>Status</th><th className={th}>Updated</th></tr></thead>
            <tbody>
              {data?.items.map((t) => (
                <tr key={t.id} className="border-b border-border last:border-0 hover:bg-ground">
                  <td className={td}>{t.number}</td>
                  <td className={td}><button type="button" className="text-left font-bold text-teal-dark underline underline-offset-2" onClick={() => setOpen(t.id)}>{t.subject}</button>{t.last_reply_by === "user" && t.status !== "solved" ? <span className="ml-2 rounded-full bg-warn-bg px-2 text-[12px] font-bold text-warn-ink">needs a reply</span> : null}</td>
                  <td className={td}>{t.email}</td><td className={td}>{categoryLabel(t.category)}</td><td className={td}>{ADMIN_STATUS_LABEL[t.status]}</td><td className={td}>{longDate(t.updated_at)}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td className={td} colSpan={6}>No tickets.</td></tr>}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <div className="mt-3 flex items-center gap-2 text-sm">
            <button type="button" className="h-10 rounded-xl border border-border px-3 font-bold disabled:opacity-50" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span>Page {page} of {pages} · {data?.total} tickets</span>
            <button type="button" className="h-10 rounded-xl border border-border px-3 font-bold disabled:opacity-50" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </section>
      {open && <Detail key={open} id={open} account={account} onChanged={reload} />}
    </>
  );
}

function Detail({ id, account, onChanged }: { id: string; account: AccountInfo; onChanged: () => void }) {
  const [t, setT] = useState<TicketThread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [email, setEmail] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    supportDesk.admin.thread(account, id).then(setT, (e) => setError((e as Error).message));
  }, [account, id]);
  if (!t) return <section className={card}><ErrorLine error={error} />{!error && <p className="text-sm text-muted">Loading…</p>}</section>;
  return (
    <section className={card} aria-labelledby="ticket-detail">
      <h2 id="ticket-detail" className={h2}>#{t.number} · {t.subject}</h2>
      <p className="mt-1 text-sm text-muted">{t.email} · {categoryLabel(t.category)} · {t.source} · {t.app} {t.version ?? ""} · page {t.page ?? "—"} · opened {longDate(t.created_at)}</p>
      {Object.keys(t.context ?? {}).length > 0 && (
        <details className="mt-2 text-sm"><summary className="cursor-pointer font-bold">What the user attached</summary><pre className="mt-1 max-h-72 overflow-auto rounded-xl bg-ground p-2 text-[12px]">{JSON.stringify(t.context, null, 2)}</pre></details>
      )}
      <ol className="mt-3 flex flex-col gap-2" aria-label="Messages">
        {t.messages.map((m) => (
          <li key={m.id} className={`rounded-xl p-3 text-sm ${m.internal ? "border border-dashed border-warn-border bg-warn-bg" : m.author === "admin" ? "border border-teal" : "bg-ground"}`}>
            <p className="text-[12px] font-bold uppercase tracking-wide text-muted">{m.internal ? "Internal note" : m.author === "admin" ? "Reply" : "User"} · {m.author_email ?? ""} · {longDate(m.at)}{m.emailed ? " · emailed" : ""}</p>
            <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
          </li>
        ))}
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={fieldLabel}>Status</span>
        {STATUSES.map((s) => (
          <button key={s} type="button" disabled={busy || t.status === s} className={`h-10 rounded-xl border px-3 text-sm font-bold disabled:opacity-60 ${t.status === s ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border bg-white"}`} onClick={async () => { setBusy(true); try { const u = await supportDesk.admin.status(account, t.id, s); setT({ ...t, ...u }); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
            {ADMIN_STATUS_LABEL[s]}
          </button>
        ))}
      </div>
      <form className="mt-3" onSubmit={async (e) => { e.preventDefault(); setBusy(true); try { const out = await supportDesk.admin.reply(account, t.id, { body, internal, email_user: email && !internal }); setT(out); setNote(internal ? "Note saved (the user never sees it)." : out.emailed ? "Reply sent and emailed from your mailbox." : out.email_note); setBody(""); onChanged(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } }}>
        <label><span className={fieldLabel}>{internal ? "Internal note" : "Reply to the user"}</span><textarea required rows={4} className="mt-1 w-full rounded-xl border border-border p-2 text-sm" value={body} onChange={(e) => setBody(e.target.value)} /></label>
        <div className="mt-2 flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={internal} onChange={() => setInternal(!internal)} /> Internal note (admins only)</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={email && !internal} disabled={internal} onChange={() => setEmail(!email)} /> Also email the user from my mailbox</label>
        </div>
        <ErrorLine error={error} />
        <button type="submit" disabled={busy || !body.trim()} className={`${primaryButton} mt-2`}>{internal ? "Save note" : "Send reply"}</button>
        {note && <span role="status" className="ml-3 text-sm font-bold text-teal-dark">{note}</span>}
      </form>
    </section>
  );
}
