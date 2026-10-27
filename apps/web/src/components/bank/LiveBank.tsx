"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import BankUpload from "@/components/bank/BankUpload";
import { EmptyState, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { getMsal, msalConfigured } from "@/lib/msal";
import {
  runtime,
  ukDate,
  type RtBankLine,
  type RtBankStatement,
  type RtBankSuggestion,
  type RtBankSummary,
  type RtUnmatchedAction,
  type RtUnmatchedLine,
} from "@/lib/runtime";

type Tab = "matches" | "unmatched" | "done";

interface Data {
  summary: RtBankSummary;
  statements: RtBankStatement[];
  suggestions: RtBankSuggestion[];
  unmatched: RtUnmatchedLine[];
  done: RtBankLine[];
}

/** Signed pence -> "−£38.47" / "£1,200.00". */
export function money(pence: number): string {
  const s = (Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${pence < 0 ? "−" : ""}£${s}`;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;
const fileName = (path: string) => path.split("/").pop() ?? path;

const ACTIONS: { action: RtUnmatchedAction; label: string }[] = [
  { action: "create_expense_proposal", label: "Create expense proposal" },
  { action: "mark_transfer", label: "Mark as transfer" },
  { action: "ignore", label: "Ignore" },
];
const DONE_LABEL: Record<string, string> = { matched: "Matched", transfer: "Transfer", ignored: "Ignored" };

async function load(a: AccountInfo): Promise<Data> {
  const [summary, statements, suggestions, unmatched, lines] = await Promise.all([
    runtime.bank.summary(a),
    runtime.bank.statements(a),
    runtime.bank.suggestions(a),
    runtime.bank.unmatched(a),
    runtime.bank.lines(a),
  ]);
  const done = lines.filter((l) => l.status === "matched" || l.status === "transfer" || l.status === "ignored").reverse();
  return { summary, statements, suggestions, unmatched, done };
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "teal" | "warn" }) {
  const box = tone === "warn" ? "border-warn-border bg-warn-bg" : tone === "teal" ? "border-teal bg-teal-tint" : "border-border bg-white";
  return (
    <div className={`rounded-2xl border p-4 ${box}`}>
      <p className={`text-sm font-semibold ${tone === "warn" ? "text-warn-ink" : "text-muted"}`}>{label}</p>
      <p className={`mt-1 text-2xl font-extrabold tracking-tight ${tone === "warn" ? "text-warn-ink" : "text-ink"}`}>{value}</p>
      <p className="mt-1 text-sm text-muted">{sub}</p>
    </div>
  );
}

function Tiles({ s }: { s: RtBankSummary }) {
  return (
    <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1100px]:grid-cols-4">
      <Tile
        label="Reconciled to date"
        value={s.reconciled_to ? ukDate(s.reconciled_to) : s.total ? "Not yet" : "—"}
        sub={s.total ? "Every bank line up to here is accounted for" : "Upload a statement to start"}
        tone="teal"
      />
      <Tile label="Matched" value={String(s.matched)} sub={`${plural(s.transfer, "transfer")} · ${s.ignored} ignored`} />
      <Tile label="To confirm" value={String(s.suggested)} sub="Suggested matches" tone={s.suggested ? "warn" : undefined} />
      <Tile label="Unmatched" value={String(s.unmatched)} sub={s.unmatched ? "Need an action" : "Nothing open"} tone={s.unmatched ? "warn" : undefined} />
    </div>
  );
}

function Statements({ list }: { list: RtBankStatement[] }) {
  if (list.length === 0) return null;
  return (
    <section aria-labelledby="statements-heading" className="rounded-2xl border border-border bg-white p-5">
      <h2 id="statements-heading" className="text-[15px] font-extrabold tracking-tight">
        Statements
      </h2>
      <ul className="mt-2 flex flex-col">
        {list.map((st) => (
          <li key={st.path} className="flex min-h-[44px] flex-wrap items-center gap-x-4 gap-y-1 border-t border-border py-2 first:border-t-0">
            <span className="min-w-0 flex-1 truncate text-[15px] font-semibold" title={st.path}>
              {fileName(st.path)}
            </span>
            <span className="text-[13px] font-medium text-muted">
              {ukDate(st.first_date)} – {ukDate(st.last_date)}
            </span>
            <span className="text-[13px] font-medium tabular-nums text-muted">
              in {money(st.money_in_pence)} · out {money(st.money_out_pence)}
            </span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[13px] font-bold ${
                st.resolved === st.lines ? "bg-teal-tint text-teal-dark" : "border border-warn-border bg-warn-bg text-warn-ink"
              }`}
            >
              {st.resolved}/{st.lines} done
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const th = "px-3 py-2";
const td = "px-3 py-3 align-top";

function LineCell({ line }: { line: RtBankLine }) {
  return (
    <>
      <td className={`${td} whitespace-nowrap`}>{ukDate(line.date)}</td>
      <td className={td}>
        <span className="font-semibold">{line.description || "—"}</span>
        {line.reference ? <span className="block text-[13px] text-muted">{line.reference}</span> : null}
      </td>
      <td className={`${td} whitespace-nowrap text-right font-bold tabular-nums`}>{money(line.amount_pence)}</td>
    </>
  );
}

function Matches({ rows, busy, act }: { rows: RtBankSuggestion[]; busy: string | null; act: Act }) {
  if (rows.length === 0) return <Empty text="No matches to confirm. New suggestions appear when you post receipts or upload statements." />;
  // "Exact" also covers a penny out; those are confirmed one by one, where the reason says so.
  const exact = rows.filter(
    (r) => r.kind === "exact" && r.events.reduce((sum, e) => sum + e.amount_pence, 0) === r.line.amount_pence,
  );
  return (
    <div className="flex flex-col gap-3">
      {exact.length > 1 && (
        <div>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act("all", async (a) => {
              for (const r of exact) await runtime.bank.confirm(a, r.line_id, r.event_ids);
              return `Confirmed ${plural(exact.length, "exact match")}.`;
            })}
            className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
          >
            {busy === "all" ? "Confirming…" : `Confirm all ${exact.length} exact matches`}
          </button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[15px]">
          <thead>
            <tr className="border-b border-border text-[13px] font-bold text-muted">
              <th scope="col" className={th}>Date</th>
              <th scope="col" className={th}>Bank line</th>
              <th scope="col" className={`${th} text-right`}>Amount</th>
              <th scope="col" className={th}>Ledger entry</th>
              <th scope="col" className={th}>Why</th>
              <th scope="col" className={th}><span className="sr-only">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.line_id} className="border-t border-border first:border-t-0">
                <LineCell line={r.line} />
                <td className={td}>
                  {r.events.map((e) => (
                    <span key={e.id} className="block">
                      <span className="font-semibold">{e.counterparty ?? "Entry"}</span>{" "}
                      <span className="text-[13px] text-muted">
                        {ukDate(e.date)} · {money(e.amount_pence)}
                      </span>
                    </span>
                  ))}
                </td>
                <td className={td}>
                  <span
                    className={`mr-2 rounded-full px-2 py-0.5 text-[12px] font-bold ${
                      r.kind === "exact" ? "bg-teal-tint text-teal-dark" : "border border-warn-border bg-warn-bg text-warn-ink"
                    }`}
                  >
                    {r.kind === "exact" ? "Exact" : "Likely"}
                  </span>
                  <span className="text-[13px] text-muted">{r.reasons.join(" · ")}</span>
                </td>
                <td className={`${td} text-right`}>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => act(r.line_id, async (a) => {
                      await runtime.bank.confirm(a, r.line_id, r.event_ids);
                      return `Matched ${r.line.description} to ${r.events[0]?.counterparty ?? "the ledger entry"}.`;
                    })}
                    aria-label={`Confirm match: ${r.line.description} ${money(r.line.amount_pence)}`}
                    className="h-10 rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                  >
                    {busy === r.line_id ? "…" : "Confirm"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Unmatched({ rows, busy, act }: { rows: RtUnmatchedLine[]; busy: string | null; act: Act }) {
  if (rows.length === 0) return <Empty text="No unmatched bank lines." />;
  function run(line: RtBankLine, action: RtUnmatchedAction) {
    act(`${line.id}:${action}`, async (a) => {
      if (action === "create_expense_proposal") {
        await runtime.bank.expenseProposal(a, line.id);
        return `Expense proposal for ${line.description} is waiting on Review.`;
      }
      if (action === "mark_transfer") {
        await runtime.bank.transfer(a, line.id);
        return `${line.description} marked as a transfer.`;
      }
      await runtime.bank.ignore(a, line.id);
      return `${line.description} ignored.`;
    });
  }
  return (
    <ul className="flex flex-col">
      {rows.map(({ line, suggested, proposal_status }) => {
        // A rejected proposal no longer counts: the user may make a fresh one.
        const pending = proposal_status === "proposed" || proposal_status === "needs_a_look";
        const posted = proposal_status === "posted";
        return (
        <li key={line.id} className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-[13px] font-medium text-muted">{ukDate(line.date)}</span>
            <span className="min-w-0 flex-1 font-semibold">{line.description || "—"}</span>
            <span className="font-bold tabular-nums">{money(line.amount_pence)}</span>
          </div>
          <p className="text-[13px] text-muted">
            {pending ? (
              <>
                An expense proposal is waiting.{" "}
                <Link href="/review" className="font-bold text-teal-dark underline underline-offset-2">
                  Approve it on Review
                </Link>{" "}
                and this line will match it.
              </>
            ) : posted ? (
              <>The expense from this line is posted but its amount or date no longer matches the line. Check it on Review.</>
            ) : (
              <>Suggested: {suggested.reason}</>
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            {ACTIONS.filter((x) => !(x.action === "create_expense_proposal" && line.amount_pence >= 0)).map((x) => {
              const primary = x.action === suggested.action && !pending && !posted;
              const waiting = x.action === "create_expense_proposal" && (pending || posted);
              return (
                <button
                  key={x.action}
                  type="button"
                  disabled={busy !== null || Boolean(waiting)}
                  onClick={() => run(line, x.action)}
                  className={`h-10 rounded-xl px-4 text-sm font-bold disabled:opacity-60 ${
                    primary ? "bg-teal text-white hover:bg-teal-dark" : "border border-border bg-white text-ink hover:bg-ground"
                  }`}
                >
                  {busy === `${line.id}:${x.action}` ? "…" : waiting ? "Proposal created" : x.label}
                </button>
              );
            })}
          </div>
        </li>
        );
      })}
    </ul>
  );
}

function Done({ rows, busy, act }: { rows: RtBankLine[]; busy: string | null; act: Act }) {
  if (rows.length === 0) return <Empty text="Nothing settled yet." />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[15px]">
        <thead>
          <tr className="border-b border-border text-[13px] font-bold text-muted">
            <th scope="col" className={th}>Date</th>
            <th scope="col" className={th}>Bank line</th>
            <th scope="col" className={`${th} text-right`}>Amount</th>
            <th scope="col" className={th}>Status</th>
            <th scope="col" className={th}><span className="sr-only">Action</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => (
            <tr key={l.id} className="border-t border-border first:border-t-0">
              <LineCell line={l} />
              <td className={td}>
                <span className="font-semibold">{DONE_LABEL[l.status]}</span>
                {l.matched_event_ids.length > 0 && (
                  <span className="block text-[12px] text-muted">{l.matched_event_ids.map((i) => i.slice(0, 8)).join(", ")}</span>
                )}
              </td>
              <td className={`${td} text-right`}>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => act(l.id, async (a) => {
                    await runtime.bank.reopen(a, l.id);
                    return `${l.description} reopened.`;
                  })}
                  className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60"
                >
                  {busy === l.id ? "…" : "Undo"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-6 text-center text-sm font-semibold text-muted">{text}</p>;
}

type Act = (key: string, run: (a: AccountInfo) => Promise<string>) => void;

/** /bank: upload statements, confirm suggested matches, settle what nothing matches. Reads and writes via the runtime. */
export default function LiveBank() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "error">("checking");
  const [data, setData] = useState<Data | null>(null);
  const [tab, setTab] = useState<Tab>("matches");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (acct: AccountInfo) => {
    try {
      setData(await load(acct));
      setError(null);
      setState("live");
    } catch (e) {
      const msg = (e as Error).message;
      if (isAuthError(msg) || isServerError(msg)) setError(msg);
      else setNote(msg);
      setState("error");
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("demo");
        setAccount(acct);
        setState("loading");
        await refresh(acct);
      } catch {
        setState("demo");
      }
    })();
  }, [refresh]);

  const act: Act = (key, run) => {
    if (!account) return;
    setBusy(key);
    setNote(null);
    setError(null);
    run(account)
      .then((msg) => setNote(msg))
      .catch((e: Error) => {
        const msg = e.message;
        if (isAuthError(msg) || isServerError(msg)) setError(msg);
        else setNote(msg);
      })
      .finally(async () => {
        await refresh(account);
        setBusy(null);
      });
  };

  if (state === "demo") {
    return (
      <p className="rounded-2xl border border-border bg-white p-5 text-[15px] font-semibold">
        <Link href="/connect" className="text-teal-dark underline underline-offset-2">
          Connect your OneDrive
        </Link>{" "}
        to import bank statements. They are saved in your own 03 Bank statements folder.
      </p>
    );
  }
  if (state === "checking" || state === "loading" || !data) {
    if (state === "error" && error) return <RuntimeErrorNote message={error} title="Could not read your bank lines" />;
    return (
      <p className="rounded-2xl border border-border bg-white p-4 text-sm font-semibold text-muted">
        {state === "error" ? `Could not read your bank lines: ${note}` : state === "loading" ? "Reading your bank lines…" : "Checking sign-in…"}
      </p>
    );
  }

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: "matches", label: "Matches", count: data.suggestions.length },
    { id: "unmatched", label: "Unmatched", count: data.unmatched.length },
    { id: "done", label: "Done", count: data.done.length },
  ];
  return (
    <div className="flex flex-col gap-5">
      <Tiles s={data.summary} />
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}
      {error && <RuntimeErrorNote message={error} />}
      {/* One uploader in a fixed place: inside the empty state it remounted after the first import and lost its result. */}
      <BankUpload account={account} onDone={() => account && refresh(account)} />
      {data.summary.total === 0 ? (
        <EmptyState
          title="No statements yet"
          body="Each payment on your statement appears here to check against your books — matching never posts anything."
        />
      ) : (
        <Statements list={data.statements} />
      )}

      {data.summary.total > 0 && (
        <section aria-label="Bank lines" className="rounded-2xl border border-border bg-white p-5">
          <div role="tablist" aria-label="Bank lines" className="flex flex-wrap gap-2 border-b border-border pb-3">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`bank-tab-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={`bank-panel-${t.id}`}
                onClick={() => setTab(t.id)}
                className={`flex h-10 items-center gap-2 rounded-xl px-4 text-[15px] font-semibold ${
                  tab === t.id ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"
                }`}
              >
                {t.label}
                <span className="rounded-full bg-ground px-2 text-[13px] font-bold tabular-nums">{t.count}</span>
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`bank-panel-${tab}`} aria-labelledby={`bank-tab-${tab}`} className="pt-2">
            {tab === "matches" && <Matches rows={data.suggestions} busy={busy} act={act} />}
            {tab === "unmatched" && <Unmatched rows={data.unmatched} busy={busy} act={act} />}
            {tab === "done" && <Done rows={data.done} busy={busy} act={act} />}
          </div>
        </section>
      )}
    </div>
  );
}
