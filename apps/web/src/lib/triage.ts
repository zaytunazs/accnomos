"use client";

import type { RtTriage } from "./runtime";

/**
 * Inbox triage state on this device only; the runtime keeps nothing.
 * localStorage: the Settings switch and the time of the last triage (no mail content).
 * sessionStorage: the last result and a reply waiting for consent, gone when the tab closes.
 */
export const TRIAGE_KEY = "accnomos.triage.mail";
export const TRIAGE_LAST_KEY = "accnomos.triage.mail.last";
const RESULT_KEY = "accnomos.triage.result";
const PENDING_DRAFT_KEY = "accnomos.triage.pending-draft";
export const TODOS_CHANGED = "accnomos:todos-changed";
export const TRIAGE_FRESH_MS = 30 * 60 * 1000; // Home re-triages when the last result is older than this

export interface LastTriage {
  at: string; // ISO time
  threads: number;
}

function get(store: () => Storage, key: string): string | null {
  try {
    return store().getItem(key);
  } catch {
    return null;
  }
}

function set(store: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) store().removeItem(key);
    else store().setItem(key, value);
  } catch {
    /* storage unavailable — lives for this page only */
  }
}

const local = () => window.localStorage;
const session = () => window.sessionStorage;

export const triageOn = () => get(local, TRIAGE_KEY) === "on";
export const setTriageOn = (on: boolean) => set(local, TRIAGE_KEY, on ? "on" : null);

export function lastTriage(): LastTriage | null {
  try {
    const raw = get(local, TRIAGE_LAST_KEY);
    return raw ? (JSON.parse(raw) as LastTriage) : null;
  } catch {
    return null;
  }
}

export function recordTriage(result: RtTriage): void {
  set(local, TRIAGE_LAST_KEY, JSON.stringify({ at: result.generated_at, threads: result.threads.length }));
  set(session, RESULT_KEY, JSON.stringify(result));
}

export function sessionTriage(): RtTriage | null {
  try {
    const raw = get(session, RESULT_KEY);
    return raw ? (JSON.parse(raw) as RtTriage) : null;
  } catch {
    return null;
  }
}

export function clearTriage(): void {
  set(local, TRIAGE_LAST_KEY, null);
  set(session, RESULT_KEY, null);
  set(session, PENDING_DRAFT_KEY, null);
}

/** A reply the user was drafting when Microsoft asked for consent (the page redirects away and back). */
export function savePendingDraft(messageId: string, body: string): void {
  set(session, PENDING_DRAFT_KEY, JSON.stringify({ messageId, body }));
}

export function takePendingDraft(): { messageId: string; body: string } | null {
  try {
    const raw = get(session, PENDING_DRAFT_KEY);
    set(session, PENDING_DRAFT_KEY, null);
    return raw ? (JSON.parse(raw) as { messageId: string; body: string }) : null;
  } catch {
    return null;
  }
}

export const todosChanged = () => window.dispatchEvent(new Event(TODOS_CHANGED));

/** "Fri 30 Oct" for a YYYY-MM-DD due date (read as a calendar day, not a UTC instant). */
export function dueLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const day = new Date(y, (m ?? 1) - 1, d ?? 1);
  return isNaN(day.getTime()) ? iso : day.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

/** True when a YYYY-MM-DD date is before today in London. */
export function overdue(iso: string): boolean {
  return iso < new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
}
