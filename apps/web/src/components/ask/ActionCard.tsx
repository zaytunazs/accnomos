"use client";

import { sentNote } from "@/lib/demo";
import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import {
  runtime,
  type RtActionResult,
  type RtBankMatchPreview,
  type RtCloseMonthPreview,
  type RtChasePreview,
  type RtClarification,
  type RtInvoicePreview,
  type RtMileagePreview,
  type RtProposedAction,
  type RtOvertimePreview,
  type RtTimesheetPreview,
} from "@/lib/runtime";
import { Markdown } from "./AnswerCard";

const gbp = (pence: number) =>
  `${pence < 0 ? "-" : ""}£${(Math.abs(pence) / 100).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const ukDate = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

/** The runtime escapes names inside its markdown; this renderer only knows **bold**, so drop the escapes. */
const unescape = (md: string) => md.replace(/\\([\\`*_[\]<>#|])/g, "$1");

/** "runtime POST /actions/approve -> 410: {"detail":"…"}" -> "…" */
function reason(e: unknown): string {
  const text = e instanceof Error ? e.message : String(e);
  const m = text.match(/-> \d+: ([\s\S]*)$/);
  if (!m) return text;
  try {
    const detail = (JSON.parse(m[1]) as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : text;
  } catch {
    return m[1];
  }
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5 text-[14px] leading-6">
      <dt className="w-24 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

const TITLES: Record<RtProposedAction["kind"], string> = {
  create_invoice: "Invoice",
  chase_invoice: "Payment reminder",
  log_timesheet: "Timesheet",
  log_mileage: "Mileage",
  match_bank_line: "Bank match",
  close_month: "Close the month",
  pay_overtime: "Overtime pay",
};

/** Where an action's result shows up, for checking after an approval that stopped halfway. */
const WHERE: Record<RtProposedAction["kind"], string> = {
  create_invoice: "Invoices",
  chase_invoice: "the invoice on Invoices",
  log_timesheet: "the job's timesheet on Jobs",
  log_mileage: "the mileage log on Vehicles",
  match_bank_line: "the line on Bank",
  close_month: "Month-end",
  pay_overtime: "the timesheet on Jobs and the next pay run on Payroll",
};

/**
 * What to do after the runtime's two 409s for an `approving` line with no result (docs/ACTIONS.md, "Once only"):
 * under 10 minutes it may still be running; after that it died and is never run again.
 */
function stalledAdvice(message: string, kind: RtProposedAction["kind"]): string {
  if (/earlier approval of this action did not finish/.test(message))
    return ` It is never retried on its own: check ${WHERE[kind]}, press Reject to clear this card, and ask again only if it is not there.`;
  if (/already being approved/.test(message))
    return ` It is never retried on its own: give it 10 minutes and check ${WHERE[kind]} before you Approve again.`;
  return "";
}
function Details({ action }: { action: RtProposedAction }) {
  if (action.kind === "create_invoice") {
    const p = action.preview as unknown as RtInvoicePreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="To">
          <strong>{p.customer.name}</strong>
          {p.send && p.send_to ? <span className="text-muted"> · {sentNote(`emailed to ${p.send_to}`)}</span> : <span className="text-muted"> · saved as a draft, not sent</span>}
        </Row>
        <Row label="For">
          <ul>
            {p.lines.map((l, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span>
                  {l.description}
                  {l.quantity !== "1" && <span className="text-muted"> × {l.quantity}</span>}
                </span>
                <span className="tabular-nums">{gbp(l.net_pence)}</span>
              </li>
            ))}
          </ul>
        </Row>
        <Row label="VAT">
          {p.vat_summary.map((v) => (
            <div key={v.vat_code} className="flex justify-between gap-3">
              <span>{v.vat_rate ? `${v.vat_rate}% on ${gbp(v.net_pence)}` : `None (${v.vat_code === "O" ? "outside the scope" : v.vat_code === "E" ? "exempt" : "zero rated"})`}</span>
              <span className="tabular-nums">{gbp(v.vat_pence)}</span>
            </div>
          ))}
        </Row>
        <Row label="Total">
          <div className="flex justify-between gap-3 font-extrabold">
            <span>Due {ukDate(p.due_date)}</span>
            <span className="tabular-nums text-teal-dark">{gbp(p.total_pence)}</span>
          </div>
        </Row>
      </dl>
    );
  }
  if (action.kind === "chase_invoice") {
    const p = action.preview as unknown as RtChasePreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="Invoice">
          <strong>{p.invoice}</strong> · {p.customer} · {gbp(p.total_pence)}
          <span className="text-muted"> · {p.days_overdue > 0 ? `${p.days_overdue} days overdue` : `due ${ukDate(p.due_date)}`}</span>
        </Row>
        <Row label="To">{p.to}</Row>
        <Row label="Subject">{p.subject}</Row>
        <Row label="Message">
          <p className="whitespace-pre-wrap rounded-xl bg-ground p-3">{p.body}</p>
        </Row>
      </dl>
    );
  }
  if (action.kind === "match_bank_line") {
    const p = action.preview as unknown as RtBankMatchPreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="Bank line">
          <strong className="tabular-nums">{gbp(p.amount_pence)}</strong> · {ukDate(p.date)} · {p.bank}
          <span className="block text-muted">{p.description}</span>
        </Row>
        <Row label="Matches">{p.to}</Row>
        {p.reasons.length > 0 && <Row label="Why">{p.reasons.join("; ")} (suggested by code)</Row>}
      </dl>
    );
  }
  if (action.kind === "close_month") {
    const p = action.preview as unknown as RtCloseMonthPreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="Month">
          <strong>{p.label}</strong>
          {p.reclose && <span className="text-muted"> · re-close</span>}
        </Row>
        <Row label="Entries">
          {p.entries} ledger entries · {p.bank_lines} bank lines
        </Row>
        <Row label="Sales">
          <span className="tabular-nums">{gbp(p.figures.sales_pence)}</span>
        </Row>
        <Row label={p.figures.net_profit_pence >= 0 ? "Net profit" : "Net loss"}>
          <strong className="tabular-nums">{gbp(p.figures.net_profit_pence)}</strong>
        </Row>
        {p.changes.length > 0 && (
          <Row label="Changed">
            <ul className="list-disc pl-5">
              {p.changes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </Row>
        )}
        <Row label="Snapshot">
          <code className="text-[13px]">{p.snapshot_hash.slice(0, 12)}</code>
        </Row>
      </dl>
    );
  }
  if (action.kind === "pay_overtime") {
    const p = action.preview as unknown as RtOvertimePreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="Who">{p.staff_name}</Row>
        {p.job_name && <Row label="Job">{p.job_name}</Row>}
        <Row label="Week">
          {ukDate(p.week_start)} – {ukDate(p.week_end)}
        </Row>
        <Row label="Hours">
          <strong className="tabular-nums">{p.hours}</strong> at {gbp(p.rate_pence)} × {p.multiplier}
        </Row>
        <Row label="Pay">
          <strong className="tabular-nums">{gbp(p.pay_pence)}</strong> ({gbp(p.extra_pence)} more), in the next pay run
        </Row>
      </dl>
    );
  }
  if (action.kind === "log_timesheet") {
    const p = action.preview as unknown as RtTimesheetPreview;
    return (
      <dl className="divide-y divide-border">
        <Row label="Who">{p.staff_name}</Row>
        <Row label="Job">{p.job_name}</Row>
        <Row label="When">{ukDate(p.date)}</Row>
        <Row label="Hours">
          <strong className="tabular-nums">{p.hours}</strong>
        </Row>
        {p.note && <Row label="Note">{p.note}</Row>}
      </dl>
    );
  }
  const p = action.preview as unknown as RtMileagePreview;
  return (
    <dl className="divide-y divide-border">
      <Row label="Vehicle">{p.vehicle_name}</Row>
      <Row label="Journey">
        {p.from} → {p.to}
      </Row>
      <Row label="When">{ukDate(p.date)}</Row>
      <Row label="Miles">
        <strong className="tabular-nums">{p.miles}</strong>
      </Row>
      {p.job_name && <Row label="Job">{p.job_name}</Row>}
    </dl>
  );
}

type State = { step: "ready" | "working" | "rejected" } | { step: "done"; result: RtActionResult } | { step: "error"; message: string };

/** A proposed action: what will happen, to whom, for how much. Nothing happens until Approve. */
export default function ActionCard({
  action,
  account,
  receivedAt,
  onChange,
  expiredText = "This proposal has expired; ask again.",
}: {
  action: RtProposedAction;
  account: AccountInfo;
  /** When the card arrived by this device's clock; absent (an older saved thread): when it was first shown. */
  receivedAt?: number;
  /** "Change": put the question back in the box so the user can reword it. Left out: no Change button. */
  onChange?: () => void;
  /** What an expired card says; Ask's default is "ask again". */
  expiredText?: string;
}) {
  const [state, setState] = useState<State>({ step: "ready" });
  const [lapsed, setLapsed] = useState(false);
  const warnings = ((action.preview.warnings as string[] | undefined) ?? []).filter(Boolean);
  const expired = lapsed && state.step === "ready";

  // Timed from when the card arrived, not by comparing the server's expiry with this device's clock, which may be off
  // (one running 15 minutes ahead would show every card as expired); a card restored from the saved thread keeps its
  // arrival time, so a reload does not restart the clock. The runtime still refuses an expired card on Approve.
  useEffect(() => {
    const ttl = Date.parse(action.expires_at) - Date.parse(action.created_at);
    const left = receivedAt === undefined ? ttl : receivedAt + ttl - Date.now();
    const t = setTimeout(() => setLapsed(true), Math.max(0, left));
    return () => clearTimeout(t);
  }, [action.created_at, action.expires_at, receivedAt]);

  async function approve() {
    setState({ step: "working" });
    try {
      setState({ step: "done", result: await runtime.approveAction(account, action) });
    } catch (e) {
      setState({ step: "error", message: reason(e) });
    }
  }

  async function reject() {
    setState({ step: "working" });
    try {
      await runtime.rejectAction(account, action);
      setState({ step: "rejected" });
    } catch (e) {
      setState({ step: "error", message: reason(e) });
    }
  }

  return (
    <article className="rounded-2xl border-2 border-teal bg-white p-5" aria-label={`Proposed: ${TITLES[action.kind]}`}>
      <p className="mb-2 text-[12px] font-bold uppercase tracking-wide text-teal-dark">
        Proposed · {TITLES[action.kind]} · needs your OK
      </p>
      <Details action={action} />

      {warnings.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {state.step === "done" ? (
        <div className="mt-4 rounded-xl bg-teal-tint p-3 text-teal-dark" role="status">
          <Markdown md={`✓ ${unescape(state.result.summary_md)}`} />
          {state.result.status === "already_done" && <p className="text-[13px]">This was already done; nothing was repeated.</p>}
        </div>
      ) : state.step === "rejected" ? (
        <p className="mt-4 text-[14px] text-muted" role="status">
          Rejected. Nothing was done.
        </p>
      ) : (
        <>
          <p className="mt-4 text-[14px] font-bold">{expired ? expiredText : `${action.confirm_text}?`}</p>
          {state.step === "error" && (
            <p className="mt-2 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink" role="alert">
              {state.message}
              {stalledAdvice(state.message, action.kind)}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={approve}
              disabled={state.step === "working" || expired}
              className="flex h-10 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50"
            >
              {state.step === "working" ? "Working…" : "Approve"}
            </button>
            {onChange && (
              <button
                type="button"
                onClick={onChange}
                disabled={state.step === "working"}
                className="flex h-10 items-center rounded-xl border border-teal px-4 text-[15px] font-bold text-teal hover:bg-teal-tint disabled:opacity-50"
              >
                Change
              </button>
            )}
            <button
              type="button"
              onClick={reject}
              disabled={state.step === "working"}
              className="flex h-10 items-center rounded-xl px-4 text-[15px] font-bold text-muted hover:bg-ground disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </>
      )}
    </article>
  );
}

/** "Which customer did you mean?" with the candidates as buttons that re-ask with the name filled in. */
export function ClarifyCard({ clarification, onPick }: { clarification: RtClarification; onPick: (name: string) => void }) {
  return (
    <article className="rounded-2xl border border-border bg-white p-5">
      <Markdown md={unescape(clarification.question_md)} />
      {clarification.candidates.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {clarification.candidates.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onPick(c)}
              className="flex h-10 items-center rounded-full border border-teal px-4 text-[14px] font-bold text-teal hover:bg-teal-tint"
            >
              {c}
            </button>
          ))}
        </div>
      )}
    </article>
  );
}

/** The question again with the user's words for the thing replaced by the picked name. */
export function withPicked(question: string, clarification: RtClarification, name: string): string {
  const ref = clarification.ref?.trim();
  if (ref) {
    const at = question.toLowerCase().indexOf(ref.toLowerCase());
    if (at >= 0) return question.slice(0, at) + name + question.slice(at + ref.length);
  }
  return `${question} (${name})`;
}
