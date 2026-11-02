"use client";

import { useEffect, useState } from "react";

/** "Show personal finances": on this device only, off by default, until profiles decide it. */
export const PERSONAL_KEY = "accnomos.personal.show";
export const PERSONAL_CHANGED = "accnomos:personal-changed";

export function personalOn(): boolean {
  try {
    return window.localStorage.getItem(PERSONAL_KEY) === "1";
  } catch {
    return false;
  }
}

export function setPersonalOn(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(PERSONAL_KEY, "1");
    else window.localStorage.removeItem(PERSONAL_KEY);
  } catch {
    /* storage unavailable — the choice lives for this page only */
  }
  window.dispatchEvent(new Event(PERSONAL_CHANGED));
}

/** Whether Personal is on for this device, kept current (Settings, another tab); the menus show it while it is. */
export function usePersonalOn(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const read = () => setOn(personalOn());
    queueMicrotask(read);
    window.addEventListener(PERSONAL_CHANGED, read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(PERSONAL_CHANGED, read);
      window.removeEventListener("storage", read);
    };
  }, []);
  return on;
}

/** "2026-11" for the month `iso` (YYYY-MM-DD) is in. */
export function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

/** The month before "2026-11": "2026-10" (January goes back to December of the year before). */
export function monthBefore(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
}

/** "November 2026" from "2026-11". */
export function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  return `${names[m - 1] ?? ""} ${y}`;
}
