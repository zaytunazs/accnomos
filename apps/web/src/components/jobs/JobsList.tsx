"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import PlanCard from "@/components/plan/PlanCard";
import SignInCta from "@/components/SignInCta";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { pence, runtime, type RtContactRow, type RtJobSummary } from "@/lib/runtime";
import { errorText, todayIso, useAccount } from "./useAccount";

const hrs = (h: number) => `${h.toLocaleString("en-GB", { maximumFractionDigits: 2 })} h`;

/** /jobs: summary tiles, the jobs table and a one-line "New job" form. */
export default function JobsList() {
  const account = useAccount();
  const [jobs, setJobs] = useState<RtJobSummary[] | null>(null);
  const [customers, setCustomers] = useState<RtContactRow[]>([]);
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [estimate, setEstimate] = useState("");
  const [filter, setFilter] = useState<"open" | "closed" | "all">("open");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"unbilled" | "name">("unbilled");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planDate, setPlanDate] = useState("");
  const [planning, setPlanning] = useState<string | null>(null);
  const newJobRef = useRef<HTMLInputElement>(null);

  const fail = useCallback((e: unknown) => {
    // Sign-in and server trouble block the page; a refusal with a reason is a note.
    const msg = errorText(e);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote(msg);
  }, []);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const [summaries, contacts] = await Promise.all([
        runtime.jobs(account),
        runtime.contacts(account).catch(() => null),
      ]);
      setJobs(summaries);
      setCustomers(contacts?.contacts.filter((c) => c.kind === "customer" || c.kind === "both") ?? []);
      setError(null);
    } catch (e) {
      fail(e);
    }
  }, [account, fail]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!account || !name.trim()) return;
    setBusy(true);
    try {
      const hours = Number(estimate);
      await runtime.createJob(account, {
        name: name.trim(), site_address: site.trim() || null, customer_id: customerId || null, status: "open",
        estimate_hours: estimate.trim() && hours > 0 ? hours : null,
      });
      setName("");
      setSite("");
      setCustomerId("");
      setEstimate("");
      setNote("Job added.");
      await load();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  if (account === null)
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
        <SignInCta />
        <span>to see the jobs in your OneDrive.</span>
      </p>
    );
  if (jobs === null && error) return <RuntimeErrorNote message={error} title="Could not read your jobs" />;
  if (jobs === null) return <LoadingSkeleton lines={4} label="Loading your jobs…" />;

  const open = jobs.filter((s) => s.job.status === "open");
  const q = query.trim().toLowerCase();
  const shown = jobs
    .filter((s) => filter === "all" || s.job.status === filter)
    .filter((s) =>
      q === "" ||
      s.job.name.toLowerCase().includes(q) ||
      (s.customer_name ?? "").toLowerCase().includes(q) ||
      (s.job.site_address ?? "").toLowerCase().includes(q),
    )
    .sort((a, b) =>
      sort === "unbilled"
        ? b.unbilled_value_pence - a.unbilled_value_pence
        : a.job.name.localeCompare(b.job.name, "en-GB"),
    );
  const sum = (f: (s: RtJobSummary) => number) => open.reduce((t, s) => t + f(s), 0);
  const tiles = [
    { label: "Open jobs", value: String(open.length), sub: `${jobs.length - open.length} closed` },
    { label: "Unbilled hours", value: hrs(sum((s) => s.unbilled_hours)), sub: "billable, not yet invoiced" },
    { label: "Unbilled value", value: pence(sum((s) => s.unbilled_value_pence)), sub: "at charge rates, ex VAT" },
    { label: "Margin so far", value: pence(sum((s) => s.margin_pence)), sub: "open jobs: value − labour − materials" },
  ];
  const card = "rounded-2xl border border-border bg-white p-4";

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1100px]:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className={card}>
            <p className="text-sm font-semibold text-muted">{t.label}</p>
            <p className="mt-1 text-2xl font-extrabold tracking-tight text-ink">{t.value}</p>
            <p className="mt-1 text-[13px] font-semibold text-muted">{t.sub}</p>
          </div>
        ))}
      </div>

      <section aria-labelledby="jobs-table" className={card}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="jobs-table" className="text-[17px] font-extrabold text-ink">
            Jobs
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm font-semibold text-muted">
              Search
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Name, customer or site"
                className="h-10 rounded-xl border border-border px-3 font-normal text-ink"
              />
            </label>
            <label className="flex items-center gap-2 text-sm font-semibold text-muted">
              Show
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as "open" | "closed" | "all")}
                className="h-10 rounded-xl border border-border bg-white px-2 font-normal text-ink"
              >
                <option value="open">Open</option>
                <option value="closed">Closed</option>
                <option value="all">All</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm font-semibold text-muted">
              Sort
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as "unbilled" | "name")}
                className="h-10 rounded-xl border border-border bg-white px-2 font-normal text-ink"
              >
                <option value="unbilled">Needs invoicing</option>
                <option value="name">Name A–Z</option>
              </select>
            </label>
          </div>
        </div>
        {shown.length === 0 ? (
          <p className="mt-3 text-sm text-muted">
            {jobs.length === 0 ? "No jobs yet. Add one below." : "No jobs match. Try another search or filter."}
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs font-bold text-muted">
                  <th scope="col" className="py-2 pr-3">Job</th>
                  <th scope="col" className="py-2 pr-3">Customer</th>
                  <th scope="col" className="py-2 pr-3 text-right">Hours</th>
                  <th scope="col" className="py-2 pr-3 text-right">Labour</th>
                  <th scope="col" className="py-2 pr-3 text-right">Materials</th>
                  <th scope="col" className="py-2 pr-3 text-right">Unbilled</th>
                  <th scope="col" className="py-2 text-right">Margin</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {shown.map((s) => (
                  <tr key={s.job.id} className="text-ink">
                    <td className="py-2 pr-3 font-bold">
                      <Link href={`/jobs/job?id=${s.job.id}`} className="text-teal-dark underline">
                        {s.job.name}
                      </Link>
                      {s.job.status === "closed" && (
                        <span className="ml-2 rounded-full bg-ground px-2 py-0.5 text-[11px] font-extrabold text-muted">Closed</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-muted">{s.customer_name ?? s.job.customer_id ?? "—"}</td>
                    <td className="py-2 pr-3 text-right">{hrs(s.hours)}</td>
                    <td className="py-2 pr-3 text-right">{pence(s.labour_cost_pence)}</td>
                    <td className="py-2 pr-3 text-right">{pence(s.materials_pence)}</td>
                    <td className="py-2 pr-3 text-right">{pence(s.unbilled_value_pence)}</td>
                    <td className={`py-2 text-right font-bold ${s.margin_pence < 0 ? "text-warn-ink" : ""}`}>{pence(s.margin_pence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {error && <RuntimeErrorNote message={error} />}
      {jobs.length === 0 && (
        <EmptyState
          title="No jobs yet"
          body="Jobs track hours, labour and materials per site, and what is still to invoice."
          action={
            <button
              type="button"
              onClick={() => newJobRef.current?.focus()}
              className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
            >
              Add your first job
            </button>
          }
        />
      )}
      {open.length > 0 &&
        (planning && account ? (
          <PlanCard account={account} date={planning} jobIds={open.map((s) => s.job.id)} onClose={() => setPlanning(null)} />
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setPlanning(planDate || todayIso());
            }}
            className={`${card} flex flex-wrap items-end gap-3`}
            aria-label="Plan a day with these jobs"
          >
            <label className="flex flex-col gap-1 text-sm font-bold text-ink">
              Day
              <input
                type="date"
                value={planDate || todayIso()}
                onChange={(e) => setPlanDate(e.target.value)}
                className="h-11 rounded-xl border border-border px-3 font-normal"
              />
            </label>
            <button type="submit" className="h-11 rounded-xl border border-teal px-5 text-[15px] font-extrabold text-teal hover:bg-teal-tint">
              Plan a day with these jobs
            </button>
            <p className="basis-full text-[13px] text-muted">
              Open jobs with a postcode, grouped by district around your calendar. Nothing is added until you approve.
            </p>
          </form>
        ))}

      <form onSubmit={create} className={`${card} flex flex-wrap items-end gap-3`} aria-label="New job">
        <label className="flex min-w-56 flex-1 flex-col gap-1 text-sm font-bold text-ink">
          New job
          <input
            ref={newJobRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Kitchen refit, 12 Elm Road"
            className="h-11 rounded-xl border border-border px-3 font-normal"
          />
        </label>
        <label className="flex min-w-56 flex-1 flex-col gap-1 text-sm font-bold text-ink">
          Site address with postcode (optional)
          <input value={site} onChange={(e) => setSite(e.target.value)} className="h-11 rounded-xl border border-border px-3 font-normal" />
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-bold text-ink">
          Customer (optional)
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="h-11 rounded-xl border border-border bg-white px-3 font-normal"
          >
            <option value="">No customer yet</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        <label className="flex w-36 flex-col gap-1 text-sm font-bold text-ink">
          Visit length (h)
          <input
            type="number"
            min="0.25"
            max="12"
            step="0.25"
            value={estimate}
            onChange={(e) => setEstimate(e.target.value)}
            placeholder="2"
            className="h-11 rounded-xl border border-border px-3 font-normal"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60"
        >
          {busy ? "Adding…" : "Add job"}
        </button>
      </form>
      {note && (
        <p role="status" aria-live="polite" className="text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </div>
  );
}
