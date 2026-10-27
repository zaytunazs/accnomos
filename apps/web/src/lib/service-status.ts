"use client";

import { RUNTIME_URL } from "./ai-config";

/** What the strip names: "api.accnomos.com" in production, the local address in development and tests. */
export function readerHost(): string {
  try {
    return new URL(RUNTIME_URL).host;
  } catch {
    return RUNTIME_URL;
  }
}

export type ReaderState = "up" | "down" | "offline";

/** Fired on window when a check passes after down/offline, so queued uploads can resume. */
export const READER_BACK = "accnomos:reader-back";

function looksOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/** GET /health, unauthenticated: "offline" when this device has no network, "down" when the reader doesn't answer. */
export async function checkReader(): Promise<ReaderState> {
  if (looksOffline()) return "offline";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(`${RUNTIME_URL}/health`, { cache: "no-store", signal: ctrl.signal });
    if (res.ok) return "up";
    return looksOffline() ? "offline" : "down";
  } catch {
    return looksOffline() ? "offline" : "down";
  } finally {
    clearTimeout(timer);
  }
}

export function announceReaderBack(): void {
  window.dispatchEvent(new Event(READER_BACK));
}
