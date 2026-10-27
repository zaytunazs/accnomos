"use client";

/**
 * The VAT period picked on /vat ("2026-Q4" etc., as GET /books/vat/periods names it), shared by the
 * live boxes, the HMRC card and Ask. Kept for this tab only (sessionStorage); null = the current period.
 */

import { useSyncExternalStore } from "react";
import { deadlinesQuery, loadBusiness } from "./business";

const KEY = "accnomos.vatPeriod";

export interface PickedPeriod {
  period: string;
  start: string; // YYYY-MM-DD
  end: string;
  label: string;
}

const listeners = new Set<() => void>();
let cached: { raw: string | null; value: PickedPeriod | null } = { raw: null, value: null };
let memory: string | null = null; // when sessionStorage is unavailable (some private modes)

function read(): PickedPeriod | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(KEY);
  } catch {
    raw = memory;
  }
  if (raw !== cached.raw) {
    let value: PickedPeriod | null = null;
    try {
      const p = raw ? (JSON.parse(raw) as PickedPeriod) : null;
      value = p && typeof p.period === "string" && /^\d{4}-\d{2}-\d{2}$/.test(p.start) && /^\d{4}-\d{2}-\d{2}$/.test(p.end) ? p : null;
    } catch {
      value = null;
    }
    cached = { raw, value };
  }
  return cached.value;
}

export function pickPeriod(p: PickedPeriod | null) {
  memory = p ? JSON.stringify(p) : null;
  try {
    if (memory) window.sessionStorage.setItem(KEY, memory);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* kept in `memory` until the page reloads */
  }
  writeUrl(p);
  listeners.forEach((l) => l());
}

const PERIOD_RE = /^\d{4}-(Q[1-4]|[01]\d)$/; // "2026-Q4" quarterly, "2026-11" monthly

/** `?period=` from the address bar, when it names a period — so a period can be linked. */
export function periodFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const p = new URLSearchParams(window.location.search).get("period");
    return p && PERIOD_RE.test(p) ? p : null;
  } catch {
    return null;
  }
}

/** Reflect the pick in `?period=` (null = the current period: the param is removed). */
function writeUrl(p: PickedPeriod | null) {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    if (p) url.searchParams.set("period", p.period);
    else url.searchParams.delete("period");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  } catch {
    /* the address bar is unavailable — the pick still lives in this tab */
  }
}

export function pickedPeriod(): PickedPeriod | null {
  return typeof window === "undefined" ? null : read();
}

export function usePickedPeriod(): PickedPeriod | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    read,
    () => null,
  );
}

/** The saved VAT settings as the runtime's query (`stagger=2`, `start_month=5`, `months=1`); "" = calendar quarters. */
export function vatQuery(): string {
  return (typeof window === "undefined" ? null : deadlinesQuery(loadBusiness())) ?? "";
}
