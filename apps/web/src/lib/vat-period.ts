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
  listeners.forEach((l) => l());
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
