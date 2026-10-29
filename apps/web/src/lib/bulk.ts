"use client";

/** Bulk upload (01 Bulk upload) and the launch check: wire types and pure timing helpers. */

export interface RtBulkRow {
  name: string;
  path: string;
  source_note: string | null;
  doc_type: string;
  supplier: string | null;
  gross: number | null;
  status: string;
  reason: string | null;
  proposal_id: string | null;
}

export interface RtBulkJob {
  id: string;
  status: string;
  created_at: string;
  rows: RtBulkRow[];
  summary: string;
  errors: { path: string; error: string }[];
}

export interface RtLaunchCheck {
  new: string[];
  changed: { path: string; reason: string }[];
  checked: number;
}

/** The document types the confirm screen offers per row. */
export const BULK_TYPES = [
  "receipt",
  "purchase_invoice",
  "sales_invoice",
  "credit_note",
  "bank_statement",
  "unclear",
] as const;

/** Once per 10 minutes per tab: sessionStorage dies with the tab, so the check reruns in a new one. */
export const LAUNCH_CHECK_INTERVAL_MS = 10 * 60 * 1000;
const LAUNCH_CHECK_KEY = "accnomos.launchCheckAt";

/** True when the launch check should run now (never ran, or the last run is older than the interval). */
export function shouldRunLaunchCheck(lastRun: number | null, now: number): boolean {
  if (lastRun === null || Number.isNaN(lastRun)) return true;
  return now - lastRun >= LAUNCH_CHECK_INTERVAL_MS;
}

export function loadLastLaunchCheck(): number | null {
  try {
    const raw = window.sessionStorage.getItem(LAUNCH_CHECK_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isNaN(n) ? null : n;
  } catch {
    return null;
  }
}

export function saveLastLaunchCheck(at: number): void {
  try {
    window.sessionStorage.setItem(LAUNCH_CHECK_KEY, String(at));
  } catch {
    /* private mode: the check simply runs every launch */
  }
}

/** "3 new, 1 changed - Review": the badge next to the launch-check progress bar. */
export function launchBadgeText(found: RtLaunchCheck): string {
  const n = found.new.length;
  const m = found.changed.length;
  const bits = [`${n} new`, `${m} changed`];
  return `${bits.join(", ")} - Review`;
}
