"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import BankReconcile, { type RulePrefillFrom } from "@/components/bank/BankReconcile";
import BankRules from "@/components/bank/BankRules";
import BankUpload from "@/components/bank/BankUpload";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import PrintButton from "@/components/PrintButton";
import { csvFilename, downloadCsv, type CsvValue } from "@/lib/csv";
import { getMsal, msalConfigured } from "@/lib/msal";
import {
  runtime,
  ukDate,
  type RtBankLine,
  type RtBankRule,
  type RtBankStatement,
  type RtBankSuggestion,
  type RtBankSummary,
  type RtUnmatchedAction,
  type RtUnmatchedLine,
} from "@/lib/runtime";

type Tab = "matches" | "unmatched" | "reconcile" | "rules" | "done";

interface Data {
  summary: RtBankSummary;
  statements: RtBankStatement[];
  suggestions: RtBankSuggestion[];
  unmatched: RtUnmatchedLine[];
  /** Every line, for the per-statement view; `done` is the settled subset. */
  lines: RtBankLine[];
  done: RtBankLine[];
}

/** Signed pence -> "−£38.47" / "£1,200.00". */
export function money(pence: number): string {
  const s = (Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${pence < 0 ? "−" : ""}£${s}`;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The runtime's three actions, plus a payout from Stripe or PayPal for money in (POST /books/bank/lines/{id}/payout). */
type LineAction = RtUnmatchedAction | "payout_stripe" | "payout_paypal";

const ACTIONS: { action: LineAction; label: string }[] = [
  { action: "create_expense_proposal", label: "Create expense proposal" },
  { action: "payout_stripe", label: "Payout from Stripe" },
  { action: "payout_paypal", label: "Payout from PayPal" },
  { action: "mark_transfer", label: "Mark as transfer" },
  { action: "ignore", label: "Ignore" },
];

const CLEARING = { payout_stripe: "1230 Stripe clearing", payout_paypal: "1240 PayPal clearing" } as const;
const DONE_LABEL: Record<string, string> = { matched: "Matched", transfer: "Transfer", ignored: "Ignored" };
const STATUS_LABEL: Record<RtBankLine["status"], string> = {
  matched: "Matched",
  suggested: "Suggested",
  unmatched: "Unmatched",
  transfer: "Transfer",
  ignored: "Ignored",
};
const STATUS_CHIP: Record<RtBankLine["status"], string> = {
  matched: "bg-teal-tint text-teal-dark",
  suggested: "border border-warn-border bg-warn-bg text-warn-ink",
  unmatched: "border border-border bg-white text-ink",
  transfer: "bg-ground text-ink",
  ignored: "bg-ground text-muted",
};

const CSV_HEAD = ["date", "description", "reference", "amount_pence", "balance_pence", "status", "match", "source_file"];

/** Every line with its status and match, money exactly as the runtime gave it (signed pence). */
function bankRows(lines: RtBankLine[]): CsvValue[][] {
  return [
    CSV_HEAD,
    ...lines.map((l) => [l.date, l.description, l.reference, l.amount_pence, l.balance_pence, l.status, l.matched_event_ids.join("; "), l.source_file]),
  ];
}

/** Paper only: every statement line, however the on-screen sections are expanded. */
function PrintLines({ lines }: { lines: RtBankLine[] }) {
  return (
    <section aria-label="Statement lines" className="hidden print:block">
      <h2 className="text-lg font-extrabold">Statement lines</h2>
      <table className="mt-2 w-full text-left text-[12px]">
        <thead>
          <tr className="border-b border-border text-left font-bold text-muted">
            <th scope="col" className="py-1 pr-2">Date</th>
            <th scope="col" className="py-1 pr-2">Description</th>
            <th scope="col" className="py-1 pr-2 text-right">Amount</th>
            <th scope="col" className="py-1 pr-2 text-right">Balance</th>
            <th scope="col" className="py-1 pr-2">Status</th>
            <th scope="col" className="py-1">Match</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.id} className="border-t border-border">
              <td className="whitespace-nowrap py-1 pr-2">{ukDate(l.date)}</td>
              <td className="py-1 pr-2">
                {l.description || "—"}
                {l.reference ? ` · ${l.reference}` : ""}
              </td>
              <td className="whitespace-nowrap py-1 pr-2 text-right font-bold tabular-nums">{money(l.amount_pence)}</td>
              <td className="whitespace-nowrap py-1 pr-2 text-right tabular-nums">{l.balance_pence === null ? "—" : money(l.balance_pence)}</td>
              <td className="py-1 pr-2">{STATUS_LABEL[l.status]}</td>
              <td className="py-1">{l.matched_event_ids.map((id) => id.slice(0, 8)).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

async function load(a: AccountInfo): Promise<Data> {
  const [summary, statements, suggestions, unmatched, lines] = await Promise.all([
    runtime.bank.summary(a),
    runtime.bank.statements(a),
    runtime.bank.suggestions(a),
    runtime.bank.unmatched(a),
    runtime.bank.lines(a),
  ]);
  const done = lines.filter((l) => l.status === "matched" || l.status === "transfer" || l.status === "ignored").reverse();
  return { summary, statements, suggestions, unmatched, lines, done };
}

function Tile({ label, value, sub, tone, hint }: { label: string; value: string; sub: string; tone?: "teal" | "warn"; hint?: string }) {
  const [showHint, setShowHint] = useState(false);
  const box = tone === "warn" ? "border-warn-border bg-warn-bg" : tone === "teal" ? "border-teal bg-teal-tint" : "border-border bg-white";
  return (
    <div className={`rounded-2xl border p-4 ${box}`}>
      <p className={`text-sm font-semibold ${tone === "warn" ? "text-warn-ink" : "text-muted"}`}>{label}</p>
      <p className={`mt-1 text-2xl font-extrabold tracking-tight ${tone === "warn" ? "text-warn-ink" : "text-ink"}`}>{value}</p>
      <p className="mt-1 text-sm text-muted">{sub}</p>
      {hint && (
        <div className="mt-1">
          <button
            type="button"
            aria-expanded={showHint}
            title={hint}
            onClick={() => setShowHint(!showHint)}
            className="text-[13px] font-bold text-teal-dark underline underline-offset-2"
          >
            {showHint ? "Hide" : "What counts?"}
          </button>
          {showHint && <p className="mt-1 text-[13px] leading-6 text-muted">{hint}</p>}
        </div>
      )}
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
        hint="Decided means matched, marked as a transfer, or ignored — every line on or before this date. Suggested matches do not count until you confirm them."
      />
      <Tile label="Matched" value={String(s.matched)} sub={`${plural(s.transfer, "transfer")} · ${s.ignored} ignored`} />
      <Tile label="To confirm" value={String(s.suggested)} sub="Suggested matches" tone={s.suggested ? "warn" : undefined} />
      <Tile label="Unmatched" value={String(s.unmatched)} sub={s.unmatched ? "Need an action" : "Nothing open"} tone={s.unmatched ? "warn" : undefined} />
    </div>
  );
}

function StatementLines({ statement, lines }: { statement: RtBankStatement; lines: RtBankLine[] }) {
  const [filter, setFilter] = useState<"all" | RtBankLine["status"]>("all");
  const rows = lines.filter((l) => l.source_file === statement.path);
  const counts = new Map<RtBankLine["status"], number>();
  for (const l of rows) counts.set(l.status, (counts.get(l.status) ?? 0) + 1);
  const shown = filter === "all" ? rows : rows.filter((l) => l.status === filter);
  const id = `statement-filter-${statement.path}`;
  return (
    <div role="region" aria-label={`Lines in ${statement.path}`} className="flex flex-col gap-2 border-t border-border py-3">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-[13px] font-bold text-muted">
          Show
        </label>
        <select
          id={id}
          value={filter}
          onChange={(e) => setFilter(e.target.value as "all" | RtBankLine["status"])}
          className="h-10 min-w-0 rounded-xl border border-border bg-white px-3 text-sm font-semibold"
        >
          <option value="all">All statuses ({rows.length})</option>
          {(Object.keys(STATUS_LABEL) as RtBankLine["status"][])
            .filter((s) => counts.has(s))
            .map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]} ({counts.get(s)})
              </option>
            ))}
        </select>
      </div>
      {shown.length === 0 ? (
        <p className="py-2 text-sm font-semibold text-muted">No lines with this status.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {shown.map((l) => (
            <li key={l.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
              <span className="text-[13px] font-medium whitespace-nowrap text-muted">{ukDate(l.date)}</span>
              <span className="min-w-0 flex-1 font-semibold">
                {l.description || "—"}
                {l.reference ? <span className="block text-[13px] font-medium text-muted">{l.reference}</span> : null}
              </span>
              <span className="font-bold whitespace-nowrap tabular-nums">{money(l.amount_pence)}</span>
              <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold whitespace-nowrap ${STATUS_CHIP[l.status]}`}>
                {STATUS_LABEL[l.status]}
              </span>
              <span className="w-full text-[13px] font-medium tabular-nums text-muted">
                Balance {l.balance_pence === null ? "—" : money(l.balance_pence)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Statements({ list, lines }: { list: RtBankStatement[]; lines: RtBankLine[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (list.length === 0) return null;
  return (
    <section aria-labelledby="statements-heading" className="rounded-2xl border border-border bg-white p-5">
      <h2 id="statements-heading" className="text-[15px] font-extrabold tracking-tight">
        Statements
      </h2>
      <ul className="mt-2 flex flex-col">
        {list.map((st) => {
          const expanded = open === st.path;
          return (
            <li key={st.path} className="border-t border-border py-2 first:border-t-0">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : st.path)}
                className="flex min-h-[44px] w-full flex-wrap items-center gap-x-4 gap-y-1 rounded-xl text-left focus-visible:bg-ground focus-visible:outline-none"
              >
                <span className="min-w-0 flex-1 truncate text-[15px] font-semibold" title={st.path}>
                  {st.path}
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
              </button>
              {expanded && <StatementLines statement={st} lines={lines} />}
            </li>
          );
        })}
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

/** Bulk confirm covers true exacts only: a penny-out or name-only suggestion stays per row, with its reason shown. */
const isBulkable = (r: RtBankSuggestion) =>
  r.kind === "exact" &&
  !r.reasons.some((reason) => reason.includes("1p out")) &&
  r.events.reduce((sum, e) => sum + e.amount_pence, 0) === r.line.amount_pence;

/** One runtime reason per chip; "exact amount, 1p out" becomes two chips so the penny shows. */
function ReasonChips({ reasons }: { reasons: string[] }) {
  const chips: { text: string; warn: boolean }[] = [];
  for (const reason of reasons) {
    const penny = /, 1p out$/.exec(reason);
    if (penny) {
      chips.push({ text: reason.slice(0, penny.index), warn: false });
      chips.push({ text: "1p out", warn: true });
    } else {
      chips.push({ text: reason, warn: false });
    }
  }
  return (
    <ul aria-label="Why this matches" className="flex flex-wrap gap-1">
      {chips.map((c, i) => (
        <li
          key={`${c.text}-${i}`}
          className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${
            c.warn ? "border border-warn-border bg-warn-bg text-warn-ink" : "bg-ground text-ink"
          }`}
        >
          {c.text}
        </li>
      ))}
    </ul>
  );
}

function KindBadge({ kind }: { kind: RtBankSuggestion["kind"] }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${
        kind === "exact" ? "bg-teal-tint text-teal-dark" : "border border-warn-border bg-warn-bg text-warn-ink"
      }`}
    >
      {kind === "exact" ? "Exact" : "Likely"}
    </span>
  );
}

function LedgerEntries({ r }: { r: RtBankSuggestion }) {
  return (
    <>
      {r.events.map((e) => (
        <span key={e.id} className="block">
          {e.label ? (
            <span className="font-semibold">{e.label}</span>
          ) : (
            <>
              <span className="font-semibold">{e.counterparty ?? "Entry"}</span>{" "}
              <span className="text-[13px] text-muted">
                {ukDate(e.date)} · {money(e.amount_pence)}
              </span>
            </>
          )}
        </span>
      ))}
    </>
  );
}

function ConfirmMatchButton({ r, busy, onConfirm, wide }: { r: RtBankSuggestion; busy: string | null; onConfirm: () => void; wide?: boolean }) {
  return (
    <button
      type="button"
      disabled={busy !== null}
      onClick={onConfirm}
      aria-label={`Confirm match: ${r.line.description} ${money(r.line.amount_pence)}`}
      className={`h-11 rounded-xl bg-teal font-bold text-white hover:bg-teal-dark disabled:opacity-60 ${
        wide ? "w-full px-5 text-[15px]" : "px-4 text-sm"
      }`}
    >
      {busy === r.line_id ? "…" : "Confirm"}
    </button>
  );
}

function Matches({ rows, busy, act }: { rows: RtBankSuggestion[]; busy: string | null; act: Act }) {
  if (rows.length === 0) return <Empty text="No matches to confirm. New suggestions appear when you post receipts or upload statements." />;
  const exact = rows.filter(isBulkable);
  const confirm = (r: RtBankSuggestion) =>
    act(r.line_id, async (a) => {
      await runtime.bank.confirm(a, r.line_id, r.event_ids);
      return `Matched ${r.line.description} to ${r.events[0]?.counterparty ?? "the ledger entry"}.`;
    });
  return (
    <div className="flex flex-col gap-3">
      {exact.length > 1 && (
        <div>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act("all", async (a) => {
              for (const r of exact) await runtime.bank.confirm(a, r.line_id, r.event_ids);
              return `Confirmed ${exact.length} exact ${exact.length === 1 ? "match" : "matches"}.`;
            })}
            className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
          >
            {busy === "all" ? "Confirming…" : `Confirm all ${exact.length} exact matches`}
          </button>
        </div>
      )}
      {/* Phone: stacked cards. Wider screens: the table. */}
      <ul className="flex flex-col gap-3 min-[560px]:hidden">
        {rows.map((r) => (
          <li key={r.line_id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
            <div className="flex items-baseline justify-between gap-3">
              <p className="min-w-0 font-semibold">{r.line.description || "—"}</p>
              <p className="shrink-0 font-bold tabular-nums">{money(r.line.amount_pence)}</p>
            </div>
            <p className="text-[13px] font-medium text-muted">
              {ukDate(r.line.date)}
              {r.line.reference ? ` · ${r.line.reference}` : ""}
            </p>
            <div className="text-sm">
              <LedgerEntries r={r} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <KindBadge kind={r.kind} />
              <ReasonChips reasons={r.reasons} />
            </div>
            <div className="mt-1">
              <ConfirmMatchButton r={r} busy={busy} onConfirm={() => confirm(r)} wide />
            </div>
          </li>
        ))}
      </ul>
      <table className="hidden w-full text-left text-[15px] min-[560px]:table">
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
            <tr
              key={r.line_id}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "BUTTON" && busy === null) confirm(r);
              }}
              className="border-t border-border first:border-t-0 focus-visible:bg-ground focus-visible:outline-none"
            >
              <LineCell line={r.line} />
              <td className={td}>
                <LedgerEntries r={r} />
              </td>
              <td className={td}>
                <span className="flex flex-wrap items-center gap-2">
                  <KindBadge kind={r.kind} />
                  <ReasonChips reasons={r.reasons} />
                </span>
              </td>
              <td className={`${td} text-right`}>
                <ConfirmMatchButton r={r} busy={busy} onConfirm={() => confirm(r)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the confirm sheet tells the user before an unmatched action runs. Nothing here posts to the ledger. */
function effectText(line: RtBankLine, action: LineAction): string {
  if (action === "payout_stripe" || action === "payout_paypal")
    return `${money(line.amount_pence)} moves from ${CLEARING[action]} to 1200 Bank. The payments it pays out are already in your books, so it is not counted as income again.`;
  if (action === "create_expense_proposal")
    return `A ${money(Math.abs(line.amount_pence))} expense proposal with no VAT reclaimed will wait in Review.`;
  if (action === "mark_transfer")
    return `${line.description} will be marked as a transfer between your own accounts. Nothing will be booked.`;
  return `${line.description} will be ignored. Nothing will be booked.`;
}

function Unmatched({ rows, busy, act }: { rows: RtUnmatchedLine[]; busy: string | null; act: Act }) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ line: RtBankLine; action: LineAction } | null>(null);
  useEffect(() => {
    if (!sheet) return;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSheet(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [sheet]);
  if (rows.length === 0) return <Empty text="No unmatched bank lines. Upload a statement and anything new appears here for you to settle." />;
  function run(line: RtBankLine, action: LineAction) {
    setSheet(null);
    setOpenMenu(null);
    act(`${line.id}:${action}`, async (a) => {
      if (action === "payout_stripe" || action === "payout_paypal") {
        const provider = action === "payout_stripe" ? "stripe" : "paypal";
        await runtime.bank.payout(a, line.id, provider);
        return `${line.description} matched as a ${provider === "stripe" ? "Stripe" : "PayPal"} payout.`;
      }
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
  const sheetLabel = sheet ? ACTIONS.find((x) => x.action === sheet.action)?.label ?? "" : "";
  return (
    <>
      <ul className="flex flex-col">
        {rows.map(({ line, suggested, proposal_status, payout }) => {
          // A rejected proposal no longer counts: the user may make a fresh one.
          const pending = proposal_status === "proposed" || proposal_status === "needs_a_look";
          const posted = proposal_status === "posted";
          const menuOpen = openMenu === line.id;
          const items = ACTIONS.filter((x) =>
            x.action === "create_expense_proposal" ? line.amount_pence < 0
            : x.action === "payout_stripe" || x.action === "payout_paypal" ? line.amount_pence > 0
            : true,
          );
          // Money in naming Stripe or PayPal is most likely that provider paying out.
          const hinted: LineAction = payout ? (payout === "stripe" ? "payout_stripe" : "payout_paypal") : suggested.action;
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
                <>Suggested: {payout ? `Looks like a payout from ${payout === "stripe" ? "Stripe" : "PayPal"}` : suggested.reason}</>
              )}
            </p>
            <div className="relative self-start">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label={pending ? `Proposal created for ${line.description}` : `Actions for ${line.description}`}
                disabled={busy !== null || pending}
                onClick={() => setOpenMenu(menuOpen ? null : line.id)}
                className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60"
              >
                {busy && busy.startsWith(`${line.id}:`) ? "…" : pending ? "Proposal created" : "Actions ▾"}
              </button>
              {menuOpen && !pending && (
                <ul
                  role="menu"
                  aria-label={`Actions for ${line.description}`}
                  className="absolute left-0 z-10 mt-1 w-64 rounded-xl border border-border bg-white py-1 shadow-lg"
                >
                  {items.map((x) => {
                    const primary = x.action === hinted && !posted;
                    const waiting = x.action === "create_expense_proposal" && posted;
                    return (
                      <li key={x.action} role="none">
                        <button
                          type="button"
                          role="menuitem"
                          disabled={busy !== null || waiting}
                          onClick={() => setSheet({ line, action: x.action })}
                          className={`flex min-h-[44px] w-full items-center px-4 text-left text-[15px] disabled:opacity-60 ${
                            primary ? "font-bold text-teal-dark hover:bg-teal-tint" : "font-semibold hover:bg-ground"
                          }`}
                        >
                          {x.label}
                          {primary && (
                            <span className="ml-2 rounded-full bg-teal-tint px-2 py-0.5 text-[12px] font-bold text-teal-dark">
                              Suggested
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </li>
          );
        })}
      </ul>
      {sheet && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 min-[560px]:items-center" onClick={() => setSheet(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="bank-action-heading"
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl border border-border bg-white p-5"
          >
            <h2 id="bank-action-heading" className="text-[15px] font-extrabold tracking-tight">
              {sheetLabel}
            </h2>
            <p className="mt-2 text-[15px] leading-7">{effectText(sheet.line, sheet.action)}</p>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                autoFocus
                disabled={busy !== null}
                onClick={() => run(sheet.line, sheet.action)}
                className="h-11 flex-1 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setSheet(null)}
                className="h-11 flex-1 rounded-xl border border-border bg-white px-5 text-[15px] font-bold hover:bg-ground"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function UndoButton({ line, busy, act, wide }: { line: RtBankLine; busy: string | null; act: Act; wide?: boolean }) {
  return (
    <button
      type="button"
      disabled={busy !== null}
      onClick={() => act(line.id, async (a) => {
        await runtime.bank.reopen(a, line.id);
        return `${line.description} reopened.`;
      })}
      aria-label={`Reopen ${line.description} ${money(line.amount_pence)}`}
      className={`h-11 rounded-xl border border-border bg-white font-bold hover:bg-ground disabled:opacity-60 ${
        wide ? "w-full px-5 text-[15px]" : "px-4 text-sm"
      }`}
    >
      {busy === line.id ? "…" : "Undo"}
    </button>
  );
}

function Done({ rows, busy, act }: { rows: RtBankLine[]; busy: string | null; act: Act }) {
  if (rows.length === 0) return <Empty text="Nothing settled yet. Confirm a match or settle an unmatched line and it shows here." />;
  return (
    <div className="flex flex-col gap-3">
      {/* Phone: stacked cards. Wider screens: the table. */}
      <ul className="flex flex-col gap-3 min-[560px]:hidden">
        {rows.map((l) => (
          <li key={l.id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
            <div className="flex items-baseline justify-between gap-3">
              <p className="min-w-0 font-semibold">{l.description || "—"}</p>
              <p className="shrink-0 font-bold tabular-nums">{money(l.amount_pence)}</p>
            </div>
            <p className="text-[13px] font-medium text-muted">
              {ukDate(l.date)}
              {l.reference ? ` · ${l.reference}` : ""}
            </p>
            <p>
              <span className={`rounded-full px-2 py-0.5 text-[12px] font-bold ${STATUS_CHIP[l.status]}`}>
                {DONE_LABEL[l.status]}
              </span>
            </p>
            <div className="mt-1">
              <UndoButton line={l} busy={busy} act={act} wide />
            </div>
          </li>
        ))}
      </ul>
      <table className="hidden w-full text-left text-[15px] min-[560px]:table">
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
                <UndoButton line={l} busy={busy} act={act} />
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
  const [changed, setChanged] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [rulePrefill, setRulePrefill] = useState<RtBankRule | null>(null);

  const refresh = useCallback(async (acct: AccountInfo) => {
    try {
      setData(await load(acct));
      setError(null);
      setState("live");
    } catch (e) {
      const msg = (e as Error).message;
      // Sign-in and server trouble block the page; a refusal with a reason is a note.
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
      .then((msg) => {
        setNote(msg);
        setChanged(true);
      })
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

  async function rebuild() {
    if (!account) return;
    setRebuilding(true);
    try {
      await runtime.rebuild(account);
      setNote("Books.xlsx rebuilt from your ledger events.");
    } catch (e) {
      setNote(`Could not rebuild Books.xlsx: ${(e as Error).message}`);
    } finally {
      setRebuilding(false);
    }
  }

  if (state === "demo") {
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-white p-5 text-[15px] font-semibold">
        <SignInCta />
        <span className="font-normal text-muted">to import bank statements. They are saved in your own 04 Bank statements folder.</span>
      </p>
    );
  }
  if (state === "checking" || state === "loading" || !data) {
    if (state === "error" && error) return <RuntimeErrorNote message={error} title="Could not read your bank lines" />;
    if (state === "error") return <RuntimeErrorNote message={note ?? "Could not read your bank lines."} title="Could not read your bank lines" />;
    return (
      <LoadingSkeleton
        lines={4}
        label={state === "loading" ? "Reading your bank lines…" : "Checking sign-in…"}
      />
    );
  }

  async function createRuleFrom(from: RulePrefillFrom) {
    if (!account) return;
    try {
      setRulePrefill(await runtime.bank.ruleDraft(account, from.lineId, from));
      setTab("rules");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const tabs: { id: Tab; label: string; count: number | null }[] = [
    { id: "matches", label: "Matches", count: data.suggestions.length },
    { id: "unmatched", label: "Unmatched", count: data.unmatched.length },
    { id: "reconcile", label: "Reconcile", count: null },
    { id: "rules", label: "Rules", count: null },
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
      {changed && (
        <div>
          <button
            type="button"
            onClick={rebuild}
            disabled={!account || rebuilding}
            title="Regenerate Books.xlsx from the ledger event files"
            className="h-10 rounded-xl border-2 border-teal bg-white px-4 text-sm font-bold text-teal-dark disabled:opacity-60"
          >
            {rebuilding ? "Rebuilding…" : "Rebuild Books.xlsx"}
          </button>
        </div>
      )}
      {error && <RuntimeErrorNote message={error} />}
      {/* One uploader in a fixed place: inside the empty state it remounted after the first import and lost its result. */}
      <BankUpload account={account} onDone={() => account && refresh(account)} />
      {data.summary.total === 0 ? (
        <EmptyState
          title="No statements yet"
          body="Each payment on your statement appears here to check against your books — matching never posts anything."
          action={
            <button
              type="button"
              onClick={() => document.getElementById("bank-upload")?.scrollIntoView({ behavior: "smooth", block: "center" })}
              className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
            >
              Upload your first statement
            </button>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-2 print:hidden">
            <PrintButton />
            <button
              type="button"
              onClick={() => downloadCsv(csvFilename("bank"), bankRows(data.lines))}
              className="h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold"
            >
              Export CSV
            </button>
          </div>
          <Statements list={data.statements} lines={data.lines} />
          <PrintLines lines={data.lines} />
        </>
      )}

      {data.summary.total === 0 ? (
        <p className="rounded-2xl border border-border bg-white p-5 text-[15px] font-semibold print:hidden">
          Bank rules live here too: open the <strong>Rules</strong> tab below to add one before your first statement arrives.
        </p>
      ) : null}
      {
        <section aria-label="Bank lines" className="rounded-2xl border border-border bg-white p-5 print:hidden">
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
                {t.count !== null && (
                  <span className="rounded-full bg-ground px-2 text-[13px] font-bold tabular-nums">{t.count}</span>
                )}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`bank-panel-${tab}`} aria-labelledby={`bank-tab-${tab}`} aria-live="polite" className="pt-2">
            {tab === "matches" && <Matches rows={data.suggestions} busy={busy} act={act} />}
            {tab === "unmatched" && <Unmatched rows={data.unmatched} busy={busy} act={act} />}
            {tab === "reconcile" && account && (
              <BankReconcile account={account} lines={data.lines} onChanged={() => account && refresh(account)} onCreateRule={(from) => void createRuleFrom(from)} />
            )}
            {tab === "rules" && account && (
              <BankRules account={account} prefill={rulePrefill} onPrefillUsed={() => setRulePrefill(null)} />
            )}
            {tab === "done" && <Done rows={data.done} busy={busy} act={act} />}
          </div>
        </section>
      }
    </div>
  );
}
