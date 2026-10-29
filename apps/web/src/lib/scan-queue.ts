"use client";

import { useSyncExternalStore } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { runtime } from "./runtime";

/**
 * Scan 00 Inbox, one document at a time, from a store that outlives the page: the user can leave Review while it
 * runs (client-side navigation keeps this module alive) and AppShell's ScanStatus shows how far it got.
 *
 * Each document gets a time limit (SCAN_DOC_LIMIT_MS). A reading that is slower is not cancelled (the runtime keeps
 * going and files the card when the model answers); the app says so, moves on to the next document, and marks it
 * read when the answer arrives. The run therefore always ends within (documents × limit): the Scan button is never
 * left waiting on one slow model. A document still being read is not sent again for 15 minutes, so a second scan
 * cannot read it twice while the first reading is under way.
 */

export type ScanItemState = "waiting" | "reading" | "done" | "slow" | "error";

export interface ScanItem {
  path: string;
  name: string;
  state: ScanItemState;
  /** done: cards made (Autopilot approvals counted apart); error: why it was not read. */
  cards?: number;
  autopilot?: number;
  message?: string;
}

export interface ScanRun {
  items: ScanItem[];
  /** Index of the document being read now, or null. */
  current: number | null;
  running: boolean;
  /** Bumped whenever a document turns into cards (Review reloads its list on a change). */
  version: number;
  summary: string | null;
}

const DEFAULT_LIMIT_MS = 120_000;
const IN_FLIGHT_MS = 15 * 60_000;

function limitMs(): number {
  // Test builds only: a spec shortens the limit (written out so production builds fold it away).
  if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
    try {
      const v = Number(window.localStorage.getItem("accnomos.test.scan-limit-ms"));
      if (v > 0) return v;
    } catch {
      /* the default */
    }
  }
  return DEFAULT_LIMIT_MS;
}

/** Seconds, in words, for the slow-reading message. */
const inWords = (ms: number) => (ms >= 60_000 ? `${Math.round(ms / 60_000)} minute${ms >= 90_000 ? "s" : ""}` : `${Math.round(ms / 1000)} seconds`);

let run: ScanRun | null = null;
const listeners = new Set<() => void>();
const inFlight = new Map<string, number>(); // path -> when its slow reading started

function emit(next: ScanRun): void {
  run = next;
  for (const l of listeners) l();
}

function patch(i: number, item: Partial<ScanItem>, extra: Partial<ScanRun> = {}): void {
  if (!run) return;
  const items = run.items.map((x, j) => (j === i ? { ...x, ...item } : x));
  emit({ ...run, ...extra, items });
}

export function useScanRun(): ScanRun | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => run,
    () => null,
  );
}

export function scanRunning(): boolean {
  return run?.running ?? false;
}

function summarise(items: ScanItem[]): string {
  const cards = items.reduce((n, x) => n + (x.state === "done" ? (x.cards ?? 0) : 0), 0);
  const auto = items.reduce((n, x) => n + (x.state === "done" ? (x.autopilot ?? 0) : 0), 0);
  const slow = items.filter((x) => x.state === "slow").length;
  const failed = items.filter((x) => x.state === "error");
  return [
    `${cards} new proposal${cards === 1 ? "" : "s"}`,
    auto ? `${auto} approved by Autopilot` : "",
    slow ? `${slow} still being read: ${slow === 1 ? "it" : "they"} will appear in Review when done` : "",
    failed.length ? `could not read: ${failed.map((x) => `${x.name}: ${x.message}`).join(" · ")}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Start a scan unless one is running. Resolves when every document is read or has passed its time limit. */
export async function startScan(account: AccountInfo): Promise<void> {
  if (run?.running) return;
  emit({ items: [], current: null, running: true, version: run?.version ?? 0, summary: null });
  let waiting: { path: string; name: string }[];
  try {
    waiting = await runtime.inboxWaiting(account);
  } catch (e) {
    emit({ ...run!, running: false, summary: `Could not look in 00 Inbox: ${(e as Error).message}` });
    throw e;
  }
  const now = Date.now();
  for (const [p, t] of inFlight) if (now - t > IN_FLIGHT_MS) inFlight.delete(p);
  const todo = waiting.filter((w) => !inFlight.has(w.path));
  const still = waiting.length - todo.length;
  if (todo.length === 0) {
    emit({
      ...run!,
      running: false,
      summary: still
        ? `Nothing new in 00 Inbox · ${still} still being read from your last scan: ${still === 1 ? "it" : "they"} will appear in Review when done`
        : "Nothing new in 00 Inbox",
    });
    return;
  }
  emit({ ...run!, items: todo.map((w) => ({ path: w.path, name: w.name, state: "waiting" as const })) });

  const limit = limitMs();
  for (let i = 0; i < todo.length; i++) {
    patch(i, { state: "reading" }, { current: i });
    const reading = runtime.scanOne(account, todo[i].path);
    const settle = (r: Awaited<typeof reading>) => {
      const auto = r.proposals.filter((p) => p.decided_by === "autopilot").length;
      const err = r.errors[0]?.error;
      return err && r.proposals.length === 0
        ? { state: "error" as const, message: err }
        : { state: "done" as const, cards: r.proposals.length - auto, autopilot: auto };
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timedOut = new Promise<"slow">((resolve) => {
      timer = setTimeout(() => resolve("slow"), limit);
    });
    try {
      const r = await Promise.race([reading, timedOut]);
      if (r === "slow") {
        inFlight.set(todo[i].path, Date.now());
        patch(i, {
          state: "slow",
          message: `still being read after ${inWords(limit)}; it will appear in Review when done`,
        });
        const index = i;
        // The reading goes on in the runtime: when it answers, the card is in Review.
        reading.then(
          (late) => {
            inFlight.delete(todo[index].path);
            patch(index, settle(late), { version: (run?.version ?? 0) + 1 });
            if (run && !run.running) emit({ ...run, summary: summarise(run.items) });
          },
          (e: Error) => {
            inFlight.delete(todo[index].path);
            patch(index, { state: "error", message: e.message });
            if (run && !run.running) emit({ ...run, summary: summarise(run.items) });
          },
        );
      } else {
        patch(i, settle(r), { version: (run?.version ?? 0) + 1 });
      }
    } catch (e) {
      patch(i, { state: "error", message: (e as Error).message });
    } finally {
      clearTimeout(timer);
    }
  }
  emit({ ...run!, current: null, running: false, summary: summarise(run!.items) });
}

/** The last run's sentence for Review's note ("1 new proposal · …"), or "" before any run. */
export function lastScanSummary(): string {
  return run?.summary ?? "";
}
