"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import ActionCard from "@/components/ask/ActionCard";
import { Markdown } from "@/components/ask/AnswerCard";
import ByWhom from "@/components/ByWhom";
import SignInCta from "@/components/SignInCta";
import { RuntimeErrorNote } from "@/components/States";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import { intakeOn } from "@/lib/intake";
import {
  closeRunStream,
  runtime,
  type RtCloseChanges,
  type RtCloseMonth,
  type RtCloseStep,
  type RtCloseStepId,
  type RtCloseSummary,
  type RtProposedAction,
} from "@/lib/runtime";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "2026-10" -> "October 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTHS[m - 1] ?? ""} ${y}`;
}

/** The last twelve months, newest first, ending with the month before today's. */
export function recentMonths(today: string): string[] {
  let [y, m] = today.split("-").map(Number);
  const out: string[] = [];
  for (let i = 0; i < 12; i++) {
    m -= 1;
    if (m === 0) {
      m = 12;
      y -= 1;
    }
    out.push(`${y}-${String(m).padStart(2, "0")}`);
  }
  return out;
}

const STEP_TITLES: { id: RtCloseStepId; title: string; what: string }[] = [
  { id: "inbox", title: "Inbox", what: "Documents waiting in 00 Inbox or Review, and Outlook if intake is on" },
  { id: "bank", title: "Bank", what: "Statement coverage, unreconciled lines and matches suggested by code" },
  { id: "sales", title: "Sales", what: "Overdue invoices (reminders drafted) and drafts not sent" },
  { id: "purchases", title: "Purchases", what: "Bills due and supplier credits not applied" },
  { id: "payroll", title: "Payroll", what: "The month's pay run, if you use payroll" },
  { id: "vat", title: "VAT", what: "If the month ends a VAT period: the 9 boxes and the deadline (never submitted)" },
  { id: "checks", title: "Checks", what: "Uncategorised balances, duplicates, negative balances, unusual postings" },
  { id: "reports", title: "Reports", what: "P&L and balance sheet saved as a draft in 07 Reports" },
  { id: "lock", title: "Lock", what: "Mark the month closed, with a snapshot of its figures" },
];

const STATUS: Record<RtCloseStep["status"], { label: string; cls: string; icon: string }> = {
  ok: { label: "OK", cls: "bg-teal-tint text-teal-dark", icon: "✓" },
  needs_you: { label: "Needs you", cls: "bg-warn-bg text-warn-ink border border-warn-border", icon: "!" },
  blocked: { label: "Blocked", cls: "bg-ground text-muted border border-border", icon: "–" },
};

type Phase = "idle" | "running" | "done";

function StatusChip({ status }: { status: RtCloseStep["status"] }) {
  const s = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-extrabold ${s.cls}`}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}

function ChangesBanner({ changes, onRerun, running }: { changes: RtCloseChanges; onRerun: () => void; running: boolean }) {
  return (
    <section aria-labelledby="close-changes" className="rounded-2xl border-2 border-warn-border bg-warn-bg p-4 sm:p-5">
      <h2 id="close-changes" className="text-lg font-extrabold tracking-tight text-warn-ink">
        Changed since it was closed
      </h2>
      <p className="mt-1 text-[15px] leading-7 text-warn-ink">{changes.headline}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] leading-6 text-ink">
        {changes.items.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      {changes.figures.length > 0 && (
        <table className="mt-3 w-full max-w-xl text-[14px]" aria-label="The month's figures before and after">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 font-semibold">Figure</th>
              <th className="py-1 text-right font-semibold">When closed</th>
              <th className="py-1 text-right font-semibold">Now</th>
            </tr>
          </thead>
          <tbody>
            {changes.figures.map((f) => (
              <tr key={f.label} className="border-t border-warn-border">
                <td className="py-1">{f.label}</td>
                <td className="py-1 text-right tabular-nums">{f.before}</td>
                <td className="py-1 text-right font-bold tabular-nums">{f.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {changes.vat_note && <p className="mt-2 text-[13px] leading-6 text-warn-ink">{changes.vat_note}</p>}
      <button
        type="button"
        onClick={onRerun}
        disabled={running}
        className="mt-3 flex h-10 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50"
      >
        Run the close again
      </button>
    </section>
  );
}

function StepRow({
  n,
  title,
  what,
  step,
  running,
  cards,
  account,
}: {
  n: number;
  title: string;
  what: string;
  step: RtCloseStep | undefined;
  running: boolean;
  cards: RtProposedAction[];
  account: AccountInfo;
}) {
  return (
    <li className="rounded-2xl border border-border bg-white p-4 sm:p-5" aria-label={`Step ${n}: ${title}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ground text-[13px] font-extrabold text-muted">
          {n}
        </span>
        <h3 className="text-[16px] font-extrabold">{title}</h3>
        {step ? (
          <StatusChip status={step.status} />
        ) : running ? (
          <span className="text-[13px] font-semibold text-muted" role="status">
            Checking…
          </span>
        ) : (
          <span className="text-[13px] text-muted">Waiting</span>
        )}
        {step && <span className="ml-auto text-[12px] text-muted tabular-nums">{step.ms} ms</span>}
      </div>
      {!step ? (
        <p className="mt-1 text-[14px] text-muted">{what}</p>
      ) : (
        <>
          <p className="mt-2 text-[15px] leading-7">
            {step.reason}
            {step.link && (
              <>
                {" "}
                <Link href={step.link} className="font-bold text-teal-dark underline hover:text-teal">
                  Open {title === "Lock" ? "Month-end" : title === "Checks" ? "Reports" : title}
                </Link>
              </>
            )}
          </p>
          {step.found.length > 1 || (step.found.length === 1 && step.found[0].text !== step.reason) ? (
            <ul className="mt-2 space-y-1.5 text-[14px] leading-6">
              {step.found.map((f, i) => (
                <li key={i} className="flex gap-2">
                  <span
                    className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                      f.level === "blocking" ? "bg-amber" : f.level === "needs_you" ? "bg-teal" : "bg-border"
                    }`}
                    aria-hidden="true"
                  />
                  <span>
                    {f.level === "blocking" && <strong className="text-warn-ink">Blocks the close: </strong>}
                    {f.level === "note" && <span className="text-muted">Note: </span>}
                    {f.text}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {step.id === "vat" && Array.isArray(step.data.boxes) && <VatBoxes step={step} />}
          {step.checked.length > 0 && (
            <details className="mt-2 text-[13px] text-muted">
              <summary className="cursor-pointer font-semibold">What was checked</summary>
              <ul className="mt-1 list-disc pl-5">
                {step.checked.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </details>
          )}
          {cards.length > 0 && (
            <div className="mt-3 flex flex-col gap-3">
              {cards.map((c) => (
                <ActionCard key={c.id} action={c} account={account} expiredText="This card has expired; run the close again." />
              ))}
            </div>
          )}
        </>
      )}
    </li>
  );
}

function VatBoxes({ step }: { step: RtCloseStep }) {
  const boxes = step.data.boxes as { box: number; label: string; amount: string }[];
  const trail = Number(step.data.trail_total ?? 0);
  return (
    <div className="mt-3">
      <table className="w-full max-w-xl text-[14px]" aria-label={`VAT return boxes, ${String(step.data.label)}`}>
        <tbody>
          {boxes.map((b) => (
            <tr key={b.box} className="border-t border-border">
              <td className="w-10 py-1 font-bold text-muted">{b.box}</td>
              <td className="py-1">{b.label}</td>
              <td className="py-1 text-right tabular-nums">£{b.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[13px] text-muted">
        Digital links: {trail} ledger {trail === 1 ? "entry" : "entries"} on this return, each linked to its document. Due{" "}
        {String(step.data.deadline)}.
      </p>
    </div>
  );
}

/** /month-end: one button runs the close checklist; each step shows as the runtime finishes it. */
export default function MonthEnd() {
  const account = useAccount();
  const today = useMemo(() => todayIso(), []);
  const months = useMemo(() => recentMonths(today), [today]);
  const [month, setMonth] = useState<string>(months[0]);
  const [detail, setDetail] = useState<RtCloseMonth | null>(null);
  const [steps, setSteps] = useState<Partial<Record<RtCloseStepId, RtCloseStep>>>({});
  const [cards, setCards] = useState<RtProposedAction[]>([]);
  const [summary, setSummary] = useState<RtCloseSummary | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const live = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const asked = new URLSearchParams(window.location.search).get("month");
    if (asked && /^\d{4}-(0[1-9]|1[0-2])$/.test(asked)) queueMicrotask(() => setMonth(asked));
  }, []);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const d = await runtime.closeMonth(account, month, today);
      setDetail(d);
      setError(null);
      if (d.run) {
        setSteps(Object.fromEntries(d.run.steps.map((s) => [s.id, s])));
        setSummary({ summary_md: d.run.summary_md, model: d.run.summary_model, fallback_reason: d.run.summary_fallback_reason });
      } else {
        setSteps({});
        setSummary(null);
      }
      setCards([]);
      setPhase(d.run ? "done" : "idle");
    } catch (e) {
      setError(errorText(e));
    }
  }, [account, month, today]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function runClose() {
    if (!account) return;
    setPhase("running");
    setSteps({});
    setCards([]);
    setSummary(null);
    setError(null);
    try {
      const run = await closeRunStream(account, month, today, intakeOn(), {
        onStep: (s) => setSteps((prev) => ({ ...prev, [s.id]: s })),
        onSummary: setSummary,
      });
      setCards(run.actions);
      setPhase("done");
      setDetail(await runtime.closeMonth(account, month, today));
    } catch (e) {
      setError(errorText(e));
      setPhase("idle");
    }
  }

  if (account === undefined) return null;
  if (account === null)
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5">
        <p className="text-[15px] text-muted">Sign in to run the month-end close on your own books.</p>
        <SignInCta />
      </div>
    );

  const label = monthLabel(month);
  const short = label.split(" ")[0];
  const done = STEP_TITLES.filter((t) => steps[t.id]).length;
  const byId = new Map(cards.map((c) => [c.id, c]));
  const needs = Object.values(steps).reduce((n, s) => n + (s?.found.filter((f) => f.level !== "note").length ?? 0), 0);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5">
        <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
          Month
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            disabled={phase === "running"}
            className="h-11 rounded-xl border border-border bg-white px-3 text-[15px] font-semibold text-ink"
          >
            {months.map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={runClose}
          disabled={phase === "running"}
          className="flex h-11 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
        >
          {phase === "running" ? `Closing ${short}…` : `Close ${short}`}
        </button>
        <div className="min-w-0 flex-1 text-[14px] leading-6 text-muted">
          {detail?.closed && detail.closed_at ? (
            <p>
              <strong className="text-teal-dark">Closed</strong> on {new Date(detail.closed_at).toLocaleDateString("en-GB")}
              {detail.closes.length > 1 ? ` (closed ${detail.closes.length} times)` : ""}.
            </p>
          ) : detail?.run ? (
            <p>Last run {new Date(detail.run.finished_at).toLocaleString("en-GB")}.</p>
          ) : (
            <p>Not run yet for {label}.</p>
          )}
        </div>
        <ByWhom
          className="w-full"
          code="Every check, figure and card by code; nothing is posted or sent until you approve"
          ai="the summary by your AI, checked against the figures"
        />
      </div>

      {error && <RuntimeErrorNote message={error} onRetry={() => void load()} />}
      {detail?.changes && <ChangesBanner changes={detail.changes} onRerun={runClose} running={phase === "running"} />}

      <p ref={live} className="sr-only" role="status" aria-live="polite">
        {phase === "running" ? `${done} of 9 steps checked` : phase === "done" ? `Close checked: ${needs} things need you` : ""}
      </p>

      {(summary || phase !== "idle") && (
        <section aria-labelledby="close-summary" className="rounded-2xl border-2 border-teal bg-white p-4 sm:p-5">
          <h2 id="close-summary" className="text-lg font-extrabold tracking-tight">
            {label}
          </h2>
          {summary ? (
            <>
              <div className="mt-1 text-[15px] leading-7">
                <Markdown md={summary.summary_md} />
              </div>
              <p className="mt-2 text-[12px] text-muted">
                {summary.fallback_reason ? `Written by code: ${summary.fallback_reason}` : `Written by ${summary.model}; every figure checked by code.`}
              </p>
            </>
          ) : (
            <p className="mt-1 text-[15px] text-muted">
              Working through the checklist: {done} of 9 steps done.
            </p>
          )}
          {phase === "done" && detail?.run && cards.length === 0 && detail.run.cards.length > 0 && (
            <p className="mt-2 text-[13px] text-muted">
              The cards from that run are not kept on the server; run the close again to approve them.
            </p>
          )}
        </section>
      )}

      <ol className="flex flex-col gap-3" aria-label={`Close checklist for ${label}`}>
        {STEP_TITLES.map((t, i) => (
          <StepRow
            key={t.id}
            n={i + 1}
            title={t.title}
            what={t.what}
            step={steps[t.id]}
            running={phase === "running" && !steps[t.id] && STEP_TITLES.slice(0, i).every((p) => steps[p.id])}
            cards={(steps[t.id]?.proposes ?? []).map((id) => byId.get(id)).filter((c): c is RtProposedAction => !!c)}
            account={account}
          />
        ))}
      </ol>
      {phase === "done" && (
        <p className="text-[13px] text-muted">
          Run recorded in _System/close/{month}.json and in the audit trail. <ChangesLink />
        </p>
      )}
    </div>
  );
}

function ChangesLink() {
  return (
    <Link href="/audit" className="font-bold text-teal-dark underline hover:text-teal">
      Open the audit trail
    </Link>
  );
}
