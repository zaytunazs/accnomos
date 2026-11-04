"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { errorText, todayIso, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { byUrgency, goalsApi, money, plainError, type RtGoalIn, type RtGoalProgress, type RtGoalsView } from "@/lib/goals";
import { sampleGoals } from "@/lib/sample-goals";
import GoalCard, { GoalsNotePanel } from "./GoalCard";
import GoalForm, { toPence } from "./GoalForm";

/** /goals: every goal with its progress, the checked note, and the form to add or change one. */
export default function LiveGoals() {
  const account = useAccount();
  if (account === undefined) return <LoadingSkeleton lines={4} label="Loading your goals…" />;
  if (!account) return <SampleGoals />;
  return <Signed account={account} />;
}

const primary = "inline-flex h-11 items-center rounded-lg bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const secondary = "inline-flex h-11 items-center rounded-lg border border-border bg-white px-4 text-[15px] font-bold text-ink hover:bg-ground disabled:opacity-60";

function Header({ action }: { action: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[30px]">Goals &amp; progress</h1>
        <p className="mt-1 text-[15px] text-muted">
          Targets you set for the business or your household, tracked against your own books. Nothing here changes them.
        </p>
      </div>
      {action}
    </div>
  );
}

function SampleGoals() {
  const v = sampleGoals;
  return (
    <div className="flex flex-col gap-5">
      <Header action={<SignInCta />} />
      <p className="rounded-lg border border-border bg-white px-4 py-3 text-[15px] text-muted">
        <strong className="text-ink">Sample — fictional figures.</strong> These goals belong to the fictional Bramblewood
        Joinery books. Sign in, or try the demo, to set goals on your own books.
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {byUrgency(v.goals).map((p) => (
          <GoalCard key={p.goal.id} p={p} sample />
        ))}
      </div>
      <GoalsNotePanel note={v.note} sample />
    </div>
  );
}

function Signed({ account }: { account: AccountInfo }) {
  const [view, setView] = useState<RtGoalsView | null>(null);
  const [wording, setWording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      // Fast first (code's note), then the AI's note swapped in, so the cards never wait on the model.
      const fast = await goalsApi.list(account, todayIso(), false);
      setView(fast);
      if (!fast.goals.length) return;
      setWording(true);
      goalsApi.list(account, todayIso()).then(
        (full) => setView((cur) => (cur ? { ...cur, note: full.note } : full)),
        () => undefined, // keep code's note
      ).finally(() => setWording(false));
    } catch (e) {
      setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
      const hash = window.location.hash.replace(/^#goal-/, "");
      if (hash && hash !== window.location.hash) setOpen(hash);
      if (window.location.hash === "#add") setAdding(true);
    });
  }, [load]);

  useEffect(() => {
    if (!view || !open) return;
    document.getElementById(`goal-card-${open}`)?.scrollIntoView({ block: "start" });
  }, [view, open]);

  async function add(g: RtGoalIn) {
    setBusy(true);
    setFormError(null);
    try {
      await goalsApi.add(account, g);
      setAdding(false);
      setNotice(`Goal added: ${g.name}.`);
      await load();
    } catch (e) {
      setFormError(plainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !view)
    return (
      <div className="flex flex-col gap-5">
        <Header action={null} />
        <RuntimeErrorNote message={error} title="Your goals could not be loaded" onRetry={() => void load()} />
      </div>
    );
  if (!view) return <LoadingSkeleton lines={4} label="Loading your goals…" />;

  const goals = byUrgency(view.goals);
  return (
    <div className="flex flex-col gap-5">
      <Header
        action={
          adding ? null : (
            <button type="button" className={primary} onClick={() => (setAdding(true), setFormError(null))}>
              + Add a goal
            </button>
          )
        }
      />
      {notice ? (
        <p role="status" className="rounded-lg bg-[#ECFDF3] px-4 py-2.5 text-[15px] text-[#166534]">
          {notice}
        </p>
      ) : null}
      {adding ? (
        <section aria-labelledby="add-goal-title" className="rounded-xl border border-border bg-white p-4 sm:p-6">
          <h2 id="add-goal-title" className="mb-4 text-[19px] font-bold text-ink">
            Add a goal
          </h2>
          <GoalForm
            today={view.today}
            household={view.household}
            busy={busy}
            error={formError}
            onSubmit={(g) => void add(g)}
            onCancel={() => setAdding(false)}
          />
        </section>
      ) : null}
      {goals.length === 0 ? (
        <div className="rounded-xl border border-border bg-white p-6 text-center">
          <h2 className="text-[19px] font-bold text-ink">No goals yet</h2>
          <p className="mx-auto mt-1 max-w-md text-[15px] text-muted">
            Save for something, spend less on a category, keep under a limit or reach a {view.household ? "income" : "sales"}{" "}
            figure. Progress is worked out from your books.
          </p>
          {!adding ? (
            <button type="button" className={`${primary} mt-4`} onClick={() => setAdding(true)}>
              Set your first goal
            </button>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {goals.map((p) => (
            <div key={p.goal.id} id={`goal-card-${p.goal.id}`} className="flex min-w-0 flex-col">
              <GoalCard
                p={p}
                footer={
                  <button
                    type="button"
                    aria-expanded={open === p.goal.id}
                    aria-controls={`goal-details-${p.goal.id}`}
                    onClick={() => setOpen(open === p.goal.id ? null : p.goal.id)}
                    className="inline-flex min-h-11 items-center text-[15px] font-bold text-teal-dark hover:underline"
                  >
                    {open === p.goal.id ? "Hide details" : "View details"}
                  </button>
                }
              />
              {open === p.goal.id ? (
                <Details
                  p={p}
                  account={account}
                  today={view.today}
                  household={view.household}
                  onChanged={async (msg) => {
                    setNotice(msg);
                    await load();
                  }}
                />
              ) : null}
            </div>
          ))}
        </div>
      )}
      <GoalsNotePanel note={view.note} wording={wording} />
      {error ? <RuntimeErrorNote message={error} onRetry={() => void load()} /> : null}
    </div>
  );
}

function Details({
  p,
  account,
  today,
  household,
  onChanged,
}: {
  p: RtGoalProgress;
  account: AccountInfo;
  today: string;
  household: boolean;
  onChanged: (msg: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [put, setPut] = useState("");
  const g = p.goal;

  async function run(work: () => Promise<unknown>, msg: string) {
    setBusy(true);
    setErr(null);
    try {
      await work();
      setEditing(false);
      setConfirming(false);
      setPut("");
      await onChanged(msg);
    } catch (e) {
      setErr(plainError(e));
    } finally {
      setBusy(false);
    }
  }

  function record() {
    const pence = toPence(put);
    if (!pence) return setErr("Enter the amount put aside in pounds, for example 50.");
    void run(() => goalsApi.patch(account, g.id, { saved_pence: g.saved_pence + pence }), `Recorded ${money(pence)} put aside for ${g.name}.`);
  }

  return (
    <section
      id={`goal-details-${g.id}`}
      aria-label={`${g.name} details`}
      className="mt-2 flex flex-col gap-4 rounded-xl border border-border bg-white p-4 sm:p-5"
    >
      {p.baseline_label ? <p className="text-[13px] text-muted">Compared with: {p.baseline_label}</p> : null}
      {p.drivers.length ? (
        <div className="min-w-0">
          <h4 className="text-[15px] font-bold text-ink">Biggest movers</h4>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-[13px] tabular-nums">
              <caption className="sr-only">Spending that moved most, against the same number of days before</caption>
              <thead className="bg-[#F3F6F8] text-left text-muted">
                <tr>
                  <th scope="col" className="px-2 py-1.5 font-semibold">What</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-semibold">So far</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-semibold">Days before</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-semibold">Change</th>
                </tr>
              </thead>
              <tbody>
                {p.drivers.map((d) => (
                  <tr key={`${d.kind}-${d.name}`} className="border-t border-border">
                    <th scope="row" className="px-2 py-1.5 text-left font-normal text-ink">
                      {d.name} <span className="text-muted">({d.kind})</span>
                    </th>
                    <td className="px-2 py-1.5 text-right">{money(d.this_pence)}</td>
                    <td className="px-2 py-1.5 text-right">{money(d.before_pence)}</td>
                    <td className="px-2 py-1.5 text-right">
                      {d.change_pence > 0 ? "+" : ""}
                      {money(d.change_pence)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      {p.suggestions.length ? (
        <div>
          <h4 className="text-[15px] font-bold text-ink">Suggestions</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[15px] leading-6 text-ink">
            {p.suggestions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <p className="mt-1 text-[13px] text-muted">Worked out by code from your books; not financial advice.</p>
        </div>
      ) : null}

      {g.kind === "save" ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`put-${g.id}`} className="text-sm font-semibold text-ink">
            Record money put aside (£)
          </label>
          <div className="flex flex-wrap gap-2">
            <input
              id={`put-${g.id}`}
              inputMode="decimal"
              value={put}
              onChange={(e) => setPut(e.target.value)}
              className="h-11 w-36 rounded-lg border border-border bg-white px-3 text-base"
            />
            <button type="button" disabled={busy} onClick={record} className={primary}>
              Record
            </button>
          </div>
          <p className="text-[13px] text-muted">Recorded so far: {money(g.saved_pence)}.</p>
        </div>
      ) : null}

      {editing ? (
        <GoalForm
          today={today}
          household={household}
          initial={g}
          busy={busy}
          error={err}
          onCancel={() => setEditing(false)}
          onSubmit={(body) => {
            const patch: Partial<RtGoalIn> = { ...body };
            delete patch.kind; // the kind stays
            void run(() => goalsApi.patch(account, g.id, patch), `Saved ${body.name}.`);
          }}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={secondary} onClick={() => (setEditing(true), setErr(null))}>
            Edit
          </button>
          {confirming ? (
            <>
              <span className="text-[15px] text-ink">Delete this goal? Your books are not changed.</span>
              <button
                type="button"
                disabled={busy}
                className="inline-flex h-11 items-center rounded-lg bg-[#A12626] px-4 text-[15px] font-bold text-white disabled:opacity-60"
                onClick={() => void run(() => goalsApi.remove(account, g.id), `Deleted ${g.name}.`)}
              >
                Yes, delete
              </button>
              <button type="button" className={secondary} onClick={() => setConfirming(false)}>
                Keep it
              </button>
            </>
          ) : (
            <button type="button" className={secondary} onClick={() => setConfirming(true)}>
              Delete
            </button>
          )}
        </div>
      )}
      {err && !editing ? (
        <p role="alert" className="rounded-lg bg-[#FFF0F0] px-3 py-2 text-[15px] text-[#A12626]">
          {err}
        </p>
      ) : null}
    </section>
  );
}

