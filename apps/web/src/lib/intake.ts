"use client";

/** Outlook intake (F10) state on this device only; the runtime keeps nothing. */
export const INTAKE_KEY = "accnomos.intake.mail";
export const INTAKE_LAST_KEY = "accnomos.intake.mail.last";

export interface LastInboxCheck {
  at: string; // ISO time of the check
  imported: number;
}

export function intakeOn(): boolean {
  try {
    return window.localStorage.getItem(INTAKE_KEY) === "on";
  } catch {
    return false;
  }
}

export function setIntakeOn(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(INTAKE_KEY, "on");
    else window.localStorage.removeItem(INTAKE_KEY);
  } catch {
    /* storage unavailable — the toggle lives for this page only */
  }
}

export function lastInboxCheck(): LastInboxCheck | null {
  try {
    const raw = window.localStorage.getItem(INTAKE_LAST_KEY);
    return raw ? (JSON.parse(raw) as LastInboxCheck) : null;
  } catch {
    return null;
  }
}

export function recordInboxCheck(imported: number): void {
  try {
    window.localStorage.setItem(INTAKE_LAST_KEY, JSON.stringify({ at: new Date().toISOString(), imported }));
  } catch {
    /* ignore */
  }
}

/** "4 min ago", "3 h ago", "27 Oct". */
export function ago(iso: string): string {
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (isNaN(mins)) return iso;
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 24 * 60) return `${Math.round(mins / 60)} h ago`;
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
