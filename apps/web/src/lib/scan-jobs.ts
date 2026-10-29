"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, msalConfigured } from "./msal";
import { runtime, type RtDocKind, type RtScanJob } from "./runtime";

/**
 * Background scans (services/runtime/app/scan_jobs.py), followed from any page: the ids of this browser's jobs live
 * in localStorage, one poller per tab asks the runtime how each is doing (every 1.5 s while something is being read,
 * every 10 s while only the user's confirmation is missing, not at all once done), and every component reads the
 * same snapshot. Leaving the page does not stop the reading: it happens on the server.
 */

const KEY = "accnomos.scanJobs";
const KEEP_MS = 24 * 3600 * 1000; // a finished job's row stays until dismissed or a day old
const FAST_MS = 1500;
const SLOW_MS = 10_000;

export const KIND_LABEL: Record<RtDocKind, string> = {
  receipt: "Receipt",
  purchase_invoice: "Bill (purchase invoice)",
  sales_invoice: "Sales invoice",
  bank_statement: "Bank statement",
  credit_note: "Credit note",
  payslip: "Payslip",
  other: "Something else",
};
export const KINDS = Object.keys(KIND_LABEL) as RtDocKind[];

interface Tracked {
  id: string;
  at: number;
}

function readTracked(): Tracked[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "[]") as Tracked[];
    return Array.isArray(raw) ? raw.filter((t) => typeof t?.id === "string" && Date.now() - t.at < KEEP_MS) : [];
  } catch {
    return [];
  }
}

function writeTracked(list: Tracked[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list.slice(-20)));
  } catch {
    /* private mode: this tab still follows the job */
  }
}

let jobs: RtScanJob[] = [];
let account: AccountInfo | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let discovered = sessionFlag(); // looked for jobs started elsewhere once this browser session
const listeners = new Set<() => void>();
const filedListeners = new Set<(cards: number) => void>();

const filed = (j: RtScanJob) => j.files.filter((f) => f.proposal_id || f.route === "bank").length;
const cards = (j: RtScanJob) => j.files.filter((f) => f.proposal_id).length;

function sessionFlag(): boolean {
  try {
    return typeof window !== "undefined" && window.sessionStorage.getItem(`${KEY}.listed`) === "1";
  } catch {
    return false;
  }
}

function emit(next: RtScanJob[]) {
  // Only jobs this tab saw before: a finished job read back from localStorage on a page load is not news.
  const prev = new Map(jobs.map((j) => [j.id, j]));
  let more = false;
  let newCards = 0;
  for (const j of next) {
    const p = prev.get(j.id);
    if (!p) continue;
    more ||= filed(j) > filed(p);
    newCards += cards(j) - cards(p);
  }
  jobs = next;
  listeners.forEach((l) => l());
  if (more) filedListeners.forEach((l) => l(newCards));
}

/**
 * Calls `listener` each time more files reach Review, Needs a look or Bank, with how many new cards that made;
 * returns the unsubscribe.
 */
export function onScanFiled(listener: (cards: number) => void): () => void {
  filedListeners.add(listener);
  return () => void filedListeners.delete(listener);
}

async function currentAccount(): Promise<AccountInfo | null> {
  if (account) return account;
  if (!msalConfigured()) return null;
  try {
    const msal = await getMsal();
    account = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
  } catch {
    account = null;
  }
  return account;
}

function schedule(ms: number) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void tick(), ms);
}

async function tick() {
  timer = null;
  const a = await currentAccount();
  if (!a) return;
  if (!discovered) {
    discovered = true; // jobs this browser did not start (Outlook intake on another device, another tab)
    try {
      window.sessionStorage.setItem(`${KEY}.listed`, "1");
    } catch {
      /* asked again on the next page load */
    }
    try {
      const listed = await runtime.scanJobs(a);
      const known = new Set(readTracked().map((t) => t.id));
      const extra = listed.jobs.filter((j) => j.status !== "done" && !known.has(j.id));
      if (extra.length) writeTracked([...readTracked(), ...extra.map((j) => ({ id: j.id, at: Date.parse(j.created_at) || Date.now() }))]);
    } catch {
      /* the list is a convenience */
    }
  }
  const tracked = readTracked();
  const old = new Map(jobs.map((j) => [j.id, j]));
  const next: RtScanJob[] = [];
  for (const t of tracked) {
    const known = old.get(t.id);
    if (known?.status === "done") {
      next.push(known); // finished: nothing more to ask
      continue;
    }
    try {
      next.push(await runtime.scanJob(a, t.id));
    } catch (e) {
      if (/404|No such scan/.test((e as Error).message)) untrackScanJob(t.id);
      else if (known) next.push(known); // offline for a moment: keep the last answer
    }
  }
  emit(next);
  if (next.some((j) => j.status === "working")) schedule(FAST_MS);
  else if (next.some((j) => j.status === "waiting")) schedule(SLOW_MS);
}

/** Follow a job this page just started (or one Outlook intake started), and poll it now. */
export function trackScanJob(job: RtScanJob | string) {
  const id = typeof job === "string" ? job : job.id;
  if (!readTracked().some((t) => t.id === id)) writeTracked([...readTracked(), { id, at: Date.now() }]);
  if (typeof job !== "string") emit([...jobs.filter((j) => j.id !== job.id), job]);
  schedule(typeof job === "string" ? 0 : FAST_MS);
}

/** Stop showing a job (it carries on, or is finished, on the server). */
export function untrackScanJob(id: string) {
  writeTracked(readTracked().filter((t) => t.id !== id));
  emit(jobs.filter((j) => j.id !== id));
}

/** Put the latest answer in the snapshot (after a confirm), and poll again soon. */
export function updateScanJob(job: RtScanJob) {
  emit(jobs.map((j) => (j.id === job.id ? job : j)));
  schedule(FAST_MS);
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

const empty: RtScanJob[] = [];

/** Every followed job, newest last. `acct` (when the page has one) saves the poller a look-up. */
export function useScanJobs(acct?: AccountInfo | null): RtScanJob[] {
  const snapshot = useSyncExternalStore(subscribe, () => jobs, () => empty);
  useEffect(() => {
    if (acct) account = acct;
    if (!timer && readTracked().length + (discovered ? 0 : 1) > 0) schedule(0);
  }, [acct]);
  return snapshot;
}

/** Counts for the top bar: files being read, and files waiting for the user to confirm their type. */
export function scanCounts(list: RtScanJob[]): { working: number; toConfirm: number } {
  return list.reduce(
    (n, j) => ({ working: n.working + j.counts.working, toConfirm: n.toConfirm + j.counts.to_confirm }),
    { working: 0, toConfirm: 0 },
  );
}
