"use client";

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
