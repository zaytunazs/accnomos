"use client";

import { useEffect, useState } from "react";

/** "Power grid" add-on (Settings › Business): spreadsheet-style grids (AG Grid Community, MIT) for bulk review and the
 *  ledger explorer. On this device only, off by default; off, every page is exactly as before. */
export const POWER_GRID_KEY = "accnomos.powergrid.show";
export const POWER_GRID_CHANGED = "accnomos:powergrid-changed";

export function powerGridOn(): boolean {
  try {
    return window.localStorage.getItem(POWER_GRID_KEY) === "1";
  } catch {
    return false;
  }
}

export function setPowerGridOn(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(POWER_GRID_KEY, "1");
    else window.localStorage.removeItem(POWER_GRID_KEY);
  } catch {
    /* storage unavailable — the choice lives for this page only */
  }
  window.dispatchEvent(new Event(POWER_GRID_CHANGED));
}

/** Whether the add-on is on, kept current (Settings, another tab). */
export function usePowerGridOn(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const read = () => setOn(powerGridOn());
    queueMicrotask(read);
    window.addEventListener(POWER_GRID_CHANGED, read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(POWER_GRID_CHANGED, read);
      window.removeEventListener("storage", read);
    };
  }, []);
  return on;
}

/** True on screens at least `px` wide; the grids fall back to the card lists below it. */
export function useWide(px = 900): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${px}px)`);
    const read = () => setWide(mq.matches);
    queueMicrotask(read);
    mq.addEventListener("change", read);
    return () => mq.removeEventListener("change", read);
  }, [px]);
  return wide;
}
