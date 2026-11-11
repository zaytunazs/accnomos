"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { Markdown } from "@/components/ask/AnswerCard";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import TicketCard from "./TicketCard";
import { demoSession } from "@/lib/demo";
import {
  STATUS_LABEL,
  TICKET_CATEGORIES,
  categoryLabel,
  supportDesk,
  type AssistAnswer,
  type Consent,
  type PayPalHelp,
  type Ticket,
  type TicketCategory,
  type TicketThread,
} from "@/lib/support-api";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const h2 = "text-[17px] font-extrabold";
const button = "flex h-10 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50";
const ghost = "flex h-10 items-center rounded-xl border border-teal px-4 text-[15px] font-bold text-teal hover:bg-teal-tint disabled:opacity-50";
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** The Support page: the support assistant, the PayPal help panel, my tickets and their threads, and a new ticket. */
export default function SupportDesk() {
  const account = useAccount();
  if (account === undefined) return <p className="mt-6 text-muted">Loading…</p>;
  if (account === null)
    return (
      <div className={`${card} mt-6`}>
        <p className="text-[15px]">
          Sign in to ask the support assistant and raise a ticket. Without a sign-in, the{" "}
          <Link href="/help" className="font-bold text-teal-dark underline underline-offset-2">
            help centre
          </Link>{" "}
          has every guide.
        </p>
        <Link href="/connect" className={`${button} mt-3 w-fit`}>
          Sign in
        </Link>
      </div>
    );
  return <Desk account={account} />;
}

function Desk({ account }: { account: AccountInfo }) {
  const demo = !!demoSession();
  const [openId, setOpenId] = useState<string | null>(null);
  const [article, setArticle] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    queueMicrotask(() => {
      setOpenId(qs.get("ticket"));
      setArticle(qs.get("article"));
      if (qs.get("new") === "1") setShowForm(true);
    });
  }, []);

  const reload = useCallback(() => {
    if (demo) return;
    supportDesk.mine(account).then(
      (p) => {
        setTickets(p.items);
        setListError(null);
      },
      (e) => setListError(errorText(e)),
    );
  }, [account, demo]);
  useEffect(() => {
    queueMicrotask(reload);
  }, [reload]);

  const open = (id: string | null) => {
    setOpenId(id);
    const url = id ? `/support?ticket=${id}` : "/support";
    window.history.replaceState(null, "", url);
  };

  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex min-w-0 flex-col gap-5">
        <Assistant account={account} article={article} demo={demo} onCreated={() => reload()} />
        {openId && !demo && <Thread key={openId} account={account} id={openId} onClose={() => open(null)} onChanged={reload} />}
        {showForm && !demo && (
          <NewTicket
            account={account}
            onCancel={() => setShowForm(false)}
            onCreated={(t) => {
              setShowForm(false);
              reload();
              open(t.id);
            }}
          />
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-5">
        <section className={card} aria-labelledby="my-tickets">
          <div className="flex items-center justify-between gap-2">
            <h2 id="my-tickets" className={h2}>
              Your tickets
            </h2>
            {!demo && (
              <button type="button" className={ghost} onClick={() => setShowForm(true)}>
                New ticket
              </button>
            )}
          </div>
          {demo ? (
            <p className="mt-2 text-[14px] text-muted">The demo can&apos;t raise tickets: sign in with your own account to contact support.</p>
          ) : listError ? (
            <p className="mt-2 text-[14px] text-warn-ink" role="alert">
              {listError}
            </p>
          ) : tickets === null ? (
            <p className="mt-2 text-[14px] text-muted">Loading…</p>
          ) : tickets.length === 0 ? (
            <p className="mt-2 text-[14px] text-muted">No tickets yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-border" aria-label="Tickets">
              {tickets.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => open(t.id)} className={`flex w-full flex-col items-start py-2 text-left hover:bg-ground ${openId === t.id ? "bg-teal-tint" : ""}`}>
                    <span className="text-[15px] font-bold text-teal-dark">
                      #{t.number} · {t.subject}
                    </span>
                    <span className="text-[13px] text-muted">
                      <StatusBadge status={t.status} /> · {categoryLabel(t.category)} · updated {when(t.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <PayPalPanel account={account} />
        <section className={card} aria-labelledby="guides">
          <h2 id="guides" className={h2}>
            Guides
          </h2>
          <p className="mt-1 text-[14px]">
            Every step-by-step guide is in the{" "}
            <Link href="/help" className="font-bold text-teal-dark underline underline-offset-2">
              help centre
            </Link>
            .
          </p>
        </section>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: Ticket["status"] }) {
  const tone = status === "solved" ? "bg-ground text-muted" : status === "pending" ? "bg-warn-bg text-warn-ink" : "bg-teal-tint text-teal-dark";
  return <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${tone}`}>{STATUS_LABEL[status]}</span>;
}

type Turn = { q: string; a?: AssistAnswer; error?: string };

function Assistant({ account, article, demo, onCreated }: { account: AccountInfo; article: string | null; demo: boolean; onCreated: () => void }) {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(question: string, ticket = false) {
    if (!question.trim()) return;
    setBusy(true);
    setTurns((t) => [...t, { q: question }]);
    try {
      const a = await supportDesk.assist(account, question, { ticket });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: errorText(e) } : x)));
    } finally {
      setBusy(false);
      setQ("");
    }
  }
  const conversation = turns.flatMap((t) => [{ role: "user" as const, text: t.q }, ...(t.a ? [{ role: "assistant" as const, text: t.a.answer_md.slice(0, 2000) }] : [])]);
  const last = turns[turns.length - 1];

  return (
    <section className={card} aria-labelledby="assistant-h">
      <h2 id="assistant-h" className={h2}>
        Ask the support assistant
      </h2>
      <p className="mt-1 text-[14px] text-muted">
        Answers come word for word from the help centre&apos;s guides, with a link to the one used. If they don&apos;t solve it, it offers a ticket. For voice, use{" "}
        <strong>Talk to Accnomos</strong> and ask the same way.
      </p>
      <ol className="mt-3 flex flex-col gap-3" aria-label="Conversation" aria-live="polite">
        {turns.map((t, i) => (
          <li key={i} className="flex flex-col gap-2">
            <p className="self-end rounded-2xl bg-teal-tint px-3 py-2 text-[15px]">{t.q}</p>
            {t.error && (
              <p className="rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] text-warn-ink" role="alert">
                {t.error}
              </p>
            )}
            {t.a && (
              <div className="rounded-2xl border border-border p-3" data-support-answer="">
                <Markdown md={t.a.answer_md} />
                {t.a.citations.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-2" aria-label="Help articles used">
                    {t.a.citations.map((c) => (
                      <li key={c.id}>
                        <Link href={c.path} className="inline-flex h-8 items-center rounded-full border border-border px-3 text-[13px] font-bold text-teal-dark hover:bg-ground">
                          Help · {c.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
                {t.a.ticket_note && <p className="mt-2 text-[14px] text-muted">{t.a.ticket_note}</p>}
              </div>
            )}
            {t.a?.ticket_card && <TicketCard action={t.a.ticket_card} account={account} conversation={conversation} onCreated={onCreated} />}
          </li>
        ))}
      </ol>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(q);
        }}
      >
        <label className="min-w-0 flex-1">
          <span className="sr-only">Your question</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            maxLength={500}
            placeholder={article ? "What didn't work in that guide?" : "How do I…? or describe the problem"}
            className="h-11 w-full rounded-xl border border-border px-3 text-[15px]"
          />
        </label>
        <button type="submit" disabled={busy || !q.trim()} className={button}>
          {busy ? "Looking…" : "Ask"}
        </button>
      </form>
      {last?.a && !last.a.ticket_card && !demo && (
        <button type="button" className="mt-2 text-[14px] font-bold text-teal-dark underline underline-offset-2" onClick={() => void ask(last.q, true)}>
          That didn&apos;t help: create a ticket
        </button>
      )}
    </section>
  );
}

function Consents({ value, onChange }: { value: Consent; onChange: (c: Consent) => void }) {
  const tick = (k: "attach_errors" | "include_paypal" | "include_financial") => onChange({ ...value, [k]: !value[k] });
  return (
    <fieldset className="mt-3 flex flex-col gap-1.5 text-[14px]">
      <legend className="font-bold">What to attach</legend>
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={value.attach_errors} onChange={() => tick("attach_errors")} className="mt-1" />
        <span>Attach recent errors (the last error messages this tab saw; no figures)</span>
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={value.include_paypal} onChange={() => tick("include_paypal")} className="mt-1" />
        <span>Include PayPal details (connected or not, last sync, the last PayPal problem)</span>
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={value.include_financial} onChange={() => tick("include_financial")} className="mt-1" />
        <span>Include financial details (amounts you type). Off: amounts are masked.</span>
      </label>
    </fieldset>
  );
}

function NewTicket({ account, onCancel, onCreated }: { account: AccountInfo; onCancel: () => void; onCreated: (t: Ticket) => void }) {
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState<TicketCategory>("how_to");
  const [body, setBody] = useState("");
  const [consent, setConsent] = useState<Consent>({ attach_errors: true, include_paypal: false, include_financial: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className={card} aria-labelledby="new-ticket">
      <h2 id="new-ticket" className={h2}>
        New ticket
      </h2>
      <form
        className="mt-2 flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            onCreated((await supportDesk.create(account, { subject, category, body }, consent)).ticket);
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="text-[14px] font-bold">
          Summary
          <input required minLength={3} maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} className="mt-1 h-11 w-full rounded-xl border border-border px-3 text-[15px] font-normal" />
        </label>
        <label className="text-[14px] font-bold">
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value as TicketCategory)} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] font-normal">
            {TICKET_CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[14px] font-bold">
          What happened, and what you tried
          <textarea required minLength={3} maxLength={10000} rows={5} value={body} onChange={(e) => setBody(e.target.value)} className="mt-1 w-full rounded-xl border border-border p-3 text-[15px] font-normal" />
        </label>
        <Consents value={consent} onChange={setConsent} />
        {error && (
          <p className="rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] text-warn-ink" role="alert">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button type="submit" disabled={busy} className={button}>
            {busy ? "Sending…" : "Create ticket"}
          </button>
          <button type="button" onClick={onCancel} className="flex h-10 items-center rounded-xl px-4 text-[15px] font-bold text-muted hover:bg-ground">
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function Thread({ account, id, onClose, onChanged }: { account: AccountInfo; id: string; onClose: () => void; onChanged: () => void }) {
  const [t, setT] = useState<TicketThread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    supportDesk.thread(account, id).then(setT, (e) => setError(errorText(e)));
  }, [account, id]);
  return (
    <section className={card} aria-labelledby="thread-h" data-ticket-thread="">
      <div className="flex items-start justify-between gap-2">
        <h2 id="thread-h" className={h2}>
          {t ? `#${t.number} · ${t.subject}` : "Ticket"}
        </h2>
        <button type="button" onClick={onClose} className="text-[14px] font-bold text-muted underline">
          Close
        </button>
      </div>
      {error && (
        <p className="mt-2 text-[14px] text-warn-ink" role="alert">
          {error}
        </p>
      )}
      {t && (
        <>
          <p className="mt-1 text-[13px] text-muted">
            <StatusBadge status={t.status} /> · {categoryLabel(t.category)} · opened {when(t.created_at)}
          </p>
          <ol className="mt-3 flex flex-col gap-3" aria-label="Messages">
            {t.messages.map((m) => (
              <li key={m.id} className={`rounded-2xl p-3 text-[15px] leading-7 ${m.author === "admin" ? "border border-teal bg-white" : "bg-ground"}`}>
                <p className="text-[12px] font-bold uppercase tracking-wide text-muted">
                  {m.author === "admin" ? "Accnomos support" : "You"} · {when(m.at)}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
              </li>
            ))}
          </ol>
          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                setT(await supportDesk.reply(account, id, reply));
                setReply("");
                onChanged();
              } catch (err) {
                setError(errorText(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="text-[14px] font-bold">
              Reply
              <textarea required rows={3} maxLength={10000} value={reply} onChange={(e) => setReply(e.target.value)} className="mt-1 w-full rounded-xl border border-border p-3 text-[15px] font-normal" />
            </label>
            {t.status === "solved" && <p className="text-[13px] text-muted">Replying opens the ticket again.</p>}
            <button type="submit" disabled={busy || !reply.trim()} className={`${button} w-fit`}>
              {busy ? "Sending…" : "Send reply"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}

function PayPalPanel({ account }: { account: AccountInfo }) {
  const [p, setP] = useState<PayPalHelp | null>(null);
  useEffect(() => {
    supportDesk.paypal(account).then(setP, () => setP(null));
  }, [account]);
  if (!p || !p.available || (!p.connected && p.open_disputes.length === 0)) return null;
  return (
    <section className={card} aria-labelledby="paypal-help" data-paypal-help="">
      <h2 id="paypal-help" className={h2}>
        PayPal help
      </h2>
      <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-[14px]">
        <dt className="text-muted">Connection</dt>
        <dd>{p.connected ? `Connected${p.test_mode ? " (sandbox)" : ""}${p.account ? ` · ${p.account}` : ""}` : "Not connected"}</dd>
        <dt className="text-muted">Last sync</dt>
        <dd>{p.last_synced_at ? when(p.last_synced_at) : "Not synced yet"}</dd>
        <dt className="text-muted">Last problem</dt>
        <dd>{p.problem ?? "None seen"}</dd>
      </dl>
      {p.open_disputes.length > 0 && (
        <>
          <h3 className="mt-3 text-[15px] font-bold">Open disputes</h3>
          <ul className="mt-1 flex flex-col gap-1 text-[14px]">
            {p.open_disputes.map((d) => (
              <li key={d.dispute_id}>
                {d.sample ? "Sample: " : ""}
                {d.reason}
                {d.invoice ? ` · invoice ${d.invoice}` : ""}
                {d.respond_by ? ` · answer by ${new Date(`${d.respond_by}T12:00:00Z`).toLocaleDateString("en-GB")}` : ""} ·{" "}
                <Link href="/invoices" className="font-bold text-teal-dark underline">
                  Open on Invoices
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3 text-[13px] text-muted">{p.no_case_api}</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {p.links.map((l) => (
          <li key={l.url}>
            <a href={l.url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center rounded-full border border-border px-3 text-[13px] font-bold text-teal-dark hover:bg-ground">
              {l.label} ↗
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[13px]">
        <Link href="/help/paypal-help" className="font-bold text-teal-dark underline">
          Which PayPal problems go where
        </Link>
      </p>
    </section>
  );
}
