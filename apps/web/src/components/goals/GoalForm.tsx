"use client";

import { useId, useState, type FormEvent } from "react";
import type { GoalKind, RtGoal, RtGoalIn } from "@/lib/goals";

/**
 * Add or edit a goal. Four plain templates (save, spend less, keep under a limit, reach a figure); labels above
 * inputs, 44 px controls; the runtime checks the shape again and its refusal is shown under the form (`error`).
 * Editing keeps the kind: a different kind of goal is a new goal.
 */

const input = "h-11 w-full min-w-0 rounded-xl border border-border bg-white px-3 text-base text-ink";
const label = "text-sm font-semibold text-ink";
const hint = "text-[13px] text-muted";

/** "1,250.50" or "1250" -> pence; null when it is not a plain amount. */
export const toPence = (text: string): number | null => {
  const t = text.replace(/[£,\s]/g, "");
  return /^\d{1,9}(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 100) : null;
};
const fromPence = (p: number | null | undefined) => (p ? (p / 100).toFixed(2).replace(/\.00$/, "") : "");

const iso = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Europe/London" });
function defaults(kind: GoalKind, today: string): { start: string; end: string } {
  const [y, m] = today.split("-").map(Number);
  const monthStart = `${today.slice(0, 7)}-01`;
  const monthEnd = iso(new Date(Date.UTC(y, m, 0, 12)));
  if (kind === "spend_less") return { start: `${y}-01-01`, end: `${y}-12-31` };
  if (kind === "save") return { start: today, end: "" };
  return { start: monthStart, end: monthEnd };
}

export const TEMPLATES: { kind: GoalKind; title: string; business: string; household?: string }[] = [
  { kind: "save", title: "Save for something", business: "A sum put aside by a date" },
  { kind: "spend_less", title: "Spend less", business: "Cut spending by a percentage" },
  { kind: "spend_cap", title: "Keep spending under a limit", business: "A ceiling for a month or any dates" },
  { kind: "earn", title: "Reach a sales figure", business: "Sales before VAT", household: "Reach an income figure" },
];

export default function GoalForm({
  today,
  household,
  initial,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  today: string;
  household: boolean;
  initial?: RtGoal;
  busy: boolean;
  error: string | null;
  onSubmit: (g: RtGoalIn) => void;
  onCancel: () => void;
}) {
  const uid = useId();
  const [kind, setKind] = useState<GoalKind>(initial?.kind ?? "save");
  const d0 = initial ? { start: initial.start, end: initial.end } : defaults("save", today);
  const [name, setName] = useState(initial?.name ?? "");
  const [amount, setAmount] = useState(fromPence(initial?.target_pence));
  const [percent, setPercent] = useState(initial?.percent ? String(initial.percent) : "10");
  const [focus, setFocus] = useState(initial?.focus ?? "");
  const [start, setStart] = useState(d0.start);
  const [end, setEnd] = useState(d0.end);
  const [measure, setMeasure] = useState<"manual" | "net_cash">(initial?.measure ?? "manual");
  const [saved, setSaved] = useState(fromPence(initial?.saved_pence));
  const [local, setLocal] = useState<string | null>(null);

  function pick(k: GoalKind) {
    setKind(k);
    setLocal(null);
    const d = defaults(k, today);
    setStart(d.start);
    setEnd(d.end);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setLocal(null);
    const body: RtGoalIn = { name: name.trim(), kind, start, end };
    if (!body.name) return setLocal("Give the goal a name.");
    if (!start || !end) return setLocal("Choose the start and end dates.");
    if (kind === "spend_less") {
      const n = Number(percent);
      if (!Number.isInteger(n) || n < 1 || n > 90) return setLocal("The cut must be a whole percentage from 1 to 90.");
      body.percent = n;
    } else {
      const p = toPence(amount);
      if (!p) return setLocal("Enter the amount in pounds, for example 1000 or 1,250.50.");
      body.target_pence = p;
    }
    if (kind === "spend_cap" || kind === "spend_less") body.focus = focus.trim() || null;
    if (kind === "save") {
      body.measure = measure;
      const s = saved.trim() ? toPence(saved) : 0;
      if (s === null) return setLocal("Enter the amount already put aside in pounds, or leave it empty.");
      body.saved_pence = s;
    }
    onSubmit(body);
  }

  const templates = initial ? TEMPLATES.filter((t) => t.kind === initial.kind) : TEMPLATES;
  const shown = local ?? error;
  return (
    <form onSubmit={submit} aria-label={initial ? `Edit ${initial.name}` : "Add a goal"} className="flex flex-col gap-4" noValidate>
      <fieldset className="flex flex-col gap-2">
        <legend className={`${label} mb-2`}>What kind of goal?</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {templates.map((t) => {
            const on = kind === t.kind;
            return (
              <label
                key={t.kind}
                className={`flex min-h-11 cursor-pointer flex-col rounded-xl border px-3 py-2.5 ${
                  on ? "border-teal bg-teal-tint" : "border-border bg-white hover:bg-ground"
                }`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`${uid}-kind`}
                    value={t.kind}
                    checked={on}
                    disabled={Boolean(initial)}
                    onChange={() => pick(t.kind)}
                    className="h-4 w-4 accent-teal"
                  />
                  <span className="text-[15px] font-bold text-ink">
                    {t.kind === "earn" && household ? (t.household ?? t.title) : t.title}
                  </span>
                </span>
                <span className="pl-6 text-[13px] text-muted">{t.kind === "earn" && household ? "Money in on your bank" : t.business}</span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <label htmlFor={`${uid}-name`} className={label}>
            Name
          </label>
          <input
            id={`${uid}-name`}
            className={input}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            placeholder={kind === "save" ? "School fee" : kind === "spend_less" ? "Less on coffee" : kind === "spend_cap" ? "Groceries this month" : "November sales"}
          />
        </div>

        {kind === "spend_less" ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-percent`} className={label}>
              Cut by (%)
            </label>
            <input id={`${uid}-percent`} className={input} inputMode="numeric" value={percent} onChange={(e) => setPercent(e.target.value)} />
            <span className={hint}>Against the same dates a year earlier, or the days just before when there is nothing then.</span>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-amount`} className={label}>
              {kind === "save" ? "Amount to save (£)" : kind === "spend_cap" ? "Spending limit (£)" : household ? "Income target (£)" : "Sales target (£)"}
            </label>
            <input id={`${uid}-amount`} className={input} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
        )}

        {kind === "spend_cap" || kind === "spend_less" ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-focus`} className={label}>
              On what? (optional)
            </label>
            <input
              id={`${uid}-focus`}
              className={input}
              value={focus}
              maxLength={60}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="Groceries, coffee, Travel…"
            />
            <span className={hint}>A category, or a word in the supplier, item or bank line. Empty: all spending.</span>
          </div>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${uid}-start`} className={label}>
            {kind === "save" ? "Starting" : "From"}
          </label>
          <input id={`${uid}-start`} type="date" className={input} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${uid}-end`} className={label}>
            {kind === "save" ? "By" : "To"}
          </label>
          <input id={`${uid}-end`} type="date" className={input} value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>

        {kind === "save" ? (
          <>
            <fieldset className="flex flex-col gap-2 sm:col-span-2">
              <legend className={`${label} mb-1`}>How should progress be counted?</legend>
              <label className="flex min-h-11 items-center gap-2 text-[15px]">
                <input type="radio" name={`${uid}-measure`} checked={measure === "manual"} onChange={() => setMeasure("manual")} className="h-4 w-4 accent-teal" />
                I&apos;ll record what I put aside
              </label>
              <label className="flex min-h-11 items-center gap-2 text-[15px]">
                <input type="radio" name={`${uid}-measure`} checked={measure === "net_cash"} onChange={() => setMeasure("net_cash")} className="h-4 w-4 accent-teal" />
                Count money in minus money out on my bank lines
              </label>
            </fieldset>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-saved`} className={label}>
                Already put aside (£, optional)
              </label>
              <input id={`${uid}-saved`} className={input} inputMode="decimal" value={saved} onChange={(e) => setSaved(e.target.value)} />
            </div>
          </>
        ) : null}
      </div>

      {shown ? (
        <p role="alert" className="rounded-xl bg-neg-tint px-3 py-2 text-[15px] text-neg-ink">
          {shown}
        </p>
      ) : null}
      <p className={hint}>A goal only reads your books: it never posts, changes or approves anything.</p>
      <div className="flex flex-wrap gap-3">
        <button type="submit" disabled={busy} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60">
          {busy ? "Saving…" : initial ? "Save changes" : "Add goal"}
        </button>
        <button type="button" onClick={onCancel} className="h-11 rounded-xl border border-border bg-white px-5 text-[15px] font-bold text-ink hover:bg-ground">
          Cancel
        </button>
      </div>
    </form>
  );
}
