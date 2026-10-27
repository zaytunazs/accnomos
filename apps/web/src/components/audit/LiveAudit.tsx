"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "@/lib/msal";
import { csvFilename, downloadCsv, type CsvValue } from "@/lib/csv";
import SignInCta from "@/components/SignInCta";
import { EmptyState, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { runtime, type RtAuditEntry } from "@/lib/runtime";
import { SAMPLE_AUDIT_DAY, sampleAudit } from "@/lib/sample-audit";

const TZ = "Europe/London";
const RANGE_DAYS = 31;

/** Who chips: each is one GET /audit filter. Planner plans are applied by you, so its chip is the plan_* lines. */
const WHO = [
  { key: "all", label: "Everyone", q: {} },
  { key: "you", label: "You", q: { actor: "user" } },
  { key: "autopilot", label: "Autopilot", q: { actor: "autopilot" } },
  { key: "intake", label: "Intake", q: { actor: "intake" } },
  { key: "triage", label: "Triage", q: { actor: "triage" } },
  { key: "planner", label: "Planner", q: { kind: "plan" } },
] as const;
type Who = (typeof WHO)[number]["key"];

/** What: an event, or a family of events by prefix (services/runtime/app/audit_view.py `matches`). */
const KINDS: [string, string][] = [
  ["", "Everything"],
  ["approved", "Postings"],
  ["undone", "Undos"],
  ["rejected", "Rejections"],
  ["proposed", "Documents read"],
  ["invoice", "Invoices"],
  ["bank", "Bank"],
  ["mail", "Mail"],
  ["action", "Ask actions"],
  ["payroll", "Payroll"],
  ["timesheet", "Timesheets"],
  ["mileage", "Mileage"],
];

const londonDay = (iso: string) => new Date(iso).toLocaleDateString("en-CA", { timeZone: TZ });
const dayHeading = (day: string) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: TZ });
const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: TZ });
const daysBefore = (day: string, n: number) => {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
};

/** The same test as the runtime, for the signed-out sample. */
function sampleMatches(e: RtAuditEntry, q: { actor?: string; kind?: string }): boolean {
  if (q.actor && ![e.actor_kind, e.actor, e.actor.replace(/^agent:/, "")].includes(q.actor)) return false;
  if (q.kind && e.event !== q.kind && !e.event.startsWith(`${q.kind}_`)) return false;
  return true;
}

function auditRows(list: RtAuditEntry[]): CsvValue[][] {
  return [
    ["ts", "actor", "actor_kind", "who", "event", "summary", "proposal", "ledger_event", "invoice", "action", "file"],
    ...list.map((e) => [e.ts, e.actor, e.actor_kind, e.actor_label, e.event, e.summary,
      e.refs.proposal, e.refs.event, e.refs.invoice, e.refs.action, e.refs.file]),
  ];
}

function ActorChip({ entry }: { entry: RtAuditEntry }) {
  const user = entry.actor_kind === "user";
  return (
    <span className="inline-flex flex-wrap gap-1">
      <span
        title={entry.actor}
        className={`rounded-full px-2 py-0.5 text-[12px] font-extrabold ${user ? "bg-teal-tint text-teal-dark" : "bg-ground text-ink"}`}
      >
        {entry.actor_label}
        <span className="sr-only">{user ? " (a person)" : " (an agent)"}</span>
      </span>
      {entry.event.startsWith("plan_") && (
        <span className="rounded-full bg-ground px-2 py-0.5 text-[12px] font-extrabold text-ink">Planner</span>
      )}
    </span>
  );
}

const linkCls = "text-[13px] font-bold text-teal-dark underline-offset-2 hover:underline";

/** Where the line points: the Review card, the invoice, the file or folder. Ledger events have no page of their own. */
function Links({ refs }: { refs: RtAuditEntry["refs"] }) {
  const out = [];
  if (refs.proposal) out.push(<Link key="p" href={`/review#proposal-${refs.proposal}`} className={linkCls}>Review card</Link>);
  if (refs.invoice) out.push(<Link key="i" href={`/invoices?q=${encodeURIComponent(refs.invoice)}`} className={linkCls}>Invoice {refs.invoice}</Link>);
  if (refs.file) {
    const isFile = /\.[A-Za-z0-9]{2,5}$/.test(refs.file);
    out.push(<Link key="f" href={`/files?path=${encodeURIComponent(refs.file)}`} className={linkCls} title={refs.file}>{isFile ? "File" : "Folder"}</Link>);
  }
  return out.length ? <span className="flex flex-wrap gap-3">{out}</span> : null;
}

/** The audit trail: from GET /audit when signed in; one sample day otherwise. Nothing here can change a line. */
export default function LiveAudit() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "error">("checking");
  const [entries, setEntries] = useState<RtAuditEntry[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [who, setWho] = useState<Who>("all");
  const [kind, setKind] = useState("");
  const [to, setTo] = useState(() => new Date().toLocaleDateString("en-CA", { timeZone: TZ }));
  const [from, setFrom] = useState(() => daysBefore(new Date().toLocaleDateString("en-CA", { timeZone: TZ }), RANGE_DAYS));

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
      } catch {
        setState("demo");
      }
    })();
  }, []);

  const filter = useMemo(() => {
    const w: { actor?: string; kind?: string } = { ...WHO.find((x) => x.key === who)!.q };
    if (kind) w.kind = kind; // the What list wins over the Planner chip's plan_* filter
    return w;
  }, [who, kind]);

  useEffect(() => {
    if (!account || from > to) return;
    let stale = false;
    const q = new URLSearchParams({ from, to, limit: "500", ...filter });
    runtime.audit(account, q.toString()).then(
      (page) => {
        if (stale) return;
        setEntries(page.entries);
        setTruncated(page.truncated);
        setNote(null);
        setState("live");
      },
      (e: Error) => {
        if (stale) return;
        setNote(e.message);
        setState("error");
      },
    );
    return () => {
      stale = true;
    };
  }, [account, from, to, filter]);

  const live = state === "live";
  const sample = state === "demo";
  const shown = useMemo(
    () => (live ? entries : sample ? sampleAudit.filter((e) => sampleMatches(e, filter)) : []),
    [live, sample, entries, filter],
  );
  const days = useMemo(() => {
    const m = new Map<string, RtAuditEntry[]>();
    for (const e of shown) {
      const d = londonDay(e.ts);
      m.set(d, [...(m.get(d) ?? []), e]);
    }
    return [...m.entries()];
  }, [shown]);

  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1 text-sm font-bold ${active ? "border-teal bg-teal-tint text-teal-dark" : "border-border bg-white text-muted hover:text-ink"}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-border bg-white p-4 print:hidden">
        {/* One choice at a time, so a radio group: arrow keys move between chips, Tab leaves the group. */}
        <div role="radiogroup" aria-label="Who did it" className="flex flex-wrap gap-2"
          onKeyDown={(e) => {
            const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
            if (!step) return;
            e.preventDefault();
            const next = WHO[(WHO.findIndex((w) => w.key === who) + step + WHO.length) % WHO.length];
            setWho(next.key);
            (e.currentTarget.querySelector(`[data-who="${next.key}"]`) as HTMLElement | null)?.focus();
          }}>
          {WHO.map((w) => (
            <button key={w.key} type="button" role="radio" aria-checked={who === w.key} data-who={w.key}
              tabIndex={who === w.key ? 0 : -1} onClick={() => setWho(w.key)} className={chip(who === w.key)}>
              {w.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-bold text-muted">
            What
            <select value={kind} onChange={(e) => setKind(e.target.value)}
              className="h-10 rounded-xl border border-border bg-white px-3 text-[15px] text-ink">
              {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {!sample && (
            <>
              <label className="flex flex-col gap-1 text-xs font-bold text-muted">
                From
                <input type="date" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)}
                  className="h-10 rounded-xl border border-border bg-white px-3 text-[15px] text-ink" />
              </label>
              <label className="flex flex-col gap-1 text-xs font-bold text-muted">
                To
                <input type="date" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)}
                  className="h-10 rounded-xl border border-border bg-white px-3 text-[15px] text-ink" />
              </label>
            </>
          )}
          {shown.length > 0 && (
            <button
              type="button"
              onClick={() => downloadCsv(csvFilename("audit"), auditRows(shown), { sample: !live })}
              className="ml-auto shrink-0 rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold"
            >
              Export CSV
            </button>
          )}
        </div>
      </div>

      {sample && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] font-medium text-muted">
          <span>Sample day at a fictional company: {dayHeading(SAMPLE_AUDIT_DAY)}.</span>
          <SignInCta />
        </p>
      )}
      {state === "error" && note && (isAuthError(note) || isServerError(note)) ? (
        <RuntimeErrorNote message={note} title="Could not read your audit trail" />
      ) : state === "error" && note ? (
        <p role="alert" className="text-sm font-semibold text-warn-ink">Could not read your audit trail: {note}</p>
      ) : null}
      {from > to && !sample && <p role="alert" className="text-sm font-semibold text-warn-ink">The From day is after the To day.</p>}
      {truncated && live && (
        <p role="status" className="text-sm font-semibold text-muted">
          Showing the newest 500 lines. Choose a shorter range or a filter to see older ones.
        </p>
      )}

      {state === "checking" || state === "loading" ? (
        <p className="rounded-2xl border border-border bg-white p-4 text-sm font-semibold text-muted">
          {state === "loading" ? "Reading your audit trail…" : "Checking sign-in…"}
        </p>
      ) : state !== "error" && shown.length === 0 ? (
        <EmptyState title="Nothing in this range" body="Try a longer range, or Everyone and Everything." />
      ) : (
        <ol aria-label="Audit trail" className="flex flex-col gap-4">
          {days.map(([day, list]) => (
            <li key={day}>
              <h2 className="mb-2 text-sm font-extrabold uppercase tracking-wide text-muted">{dayHeading(day)}</h2>
              <ol className="divide-y divide-border rounded-2xl border border-border bg-white">
                {list.map((e, i) => (
                  <li key={`${e.ts}-${e.event}-${i}`} data-event={e.event} className="flex gap-3 px-4 py-3">
                    <time dateTime={e.ts} className="w-12 shrink-0 pt-0.5 text-[13px] font-bold tabular-nums text-muted">
                      {clock(e.ts)}
                    </time>
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <ActorChip entry={e} />
                      <p className="break-words text-[15px] text-ink">{e.summary}</p>
                      <Links refs={e.refs} />
                    </div>
                  </li>
                ))}
              </ol>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
