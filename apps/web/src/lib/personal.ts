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
