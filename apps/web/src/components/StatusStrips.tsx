"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { announceReaderBack, checkReader, readerHost, type ReaderState } from "@/lib/service-status";

const bar =
  "flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-warn-border bg-warn-bg px-4 py-2 text-center text-[13px] font-bold text-warn-ink";

const button =
  "shrink-0 whitespace-nowrap rounded-lg border border-warn-border bg-white px-3 py-1 text-[13px] font-bold text-warn-ink";

/**
 * The one shared strip for reader trouble, at the top of every page. A failed
 * /health check shows it; pages underneath keep rendering what they can
 * (samples, cached data). Retry re-checks; recovery fires `READER_BACK` so
 * queued uploads resume.
 */
export function ServiceStrip() {
  const [state, setState] = useState<ReaderState | null>(null); // null until the first check: render nothing
  const ref = useRef<ReaderState | null>(null);

  const check = useCallback(async () => {
    const next = await checkReader();
    const prev = ref.current;
    ref.current = next;
    setState(next);
    if (next === "up" && (prev === "down" || prev === "offline")) announceReaderBack();
  }, []);

  useEffect(() => {
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => void check());
    const onOffline = () => {
      ref.current = "offline";
      setState("offline");
    };
    const onOnline = () => {
      void check();
    };
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, [check]);

  if (state === null || state === "up") return null;
  return (
    <div role="alert" className={bar}>
      <span>
        {state === "offline"
          ? "You're offline — your files are safe in OneDrive. Uploads will wait and resume when you reconnect."
          : `The reader at ${readerHost()} isn't answering — your files are safe in OneDrive; try again in a minute.`}
      </span>
      <button type="button" onClick={() => void check()} className={button}>
        Try again
      </button>
    </div>
  );
}

/** How often the app re-reads /version.json (NEXT_PUBLIC_VERSION_POLL_MS inlines the override; default 10 minutes). */
const POLL_MS = Number(process.env.NEXT_PUBLIC_VERSION_POLL_MS ?? "") || 10 * 60 * 1000;

interface VersionInfo {
  sha: string;
  builtAt: string;
}

/**
 * "A new version is available — reload" when /version.json (written by the
 * deploy workflow) changes under a running tab. Missing file, bad JSON or a
 * failed fetch all stay quiet: most builds predate the file.
 */
export function VersionStrip() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    let baseline: string | null = null;
    let live = true;
    async function poll() {
      if (document.hidden) return; // a hidden tab waits its turn
      try {
        const res = await fetch("/version.json", { cache: "no-store" });
        if (!res.ok) return;
        const info = (await res.json()) as Partial<VersionInfo>;
        if (typeof info.sha !== "string" || info.sha === "") return;
        if (baseline === null) baseline = info.sha;
        else if (live && info.sha !== baseline) setShow(true);
      } catch {
        /* no version file yet, or unreachable: stay quiet */
      }
    }
    void poll();
    const id = setInterval(() => void poll(), POLL_MS);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);

  if (!show) return null;
  return (
    <div role="status" className={bar}>
      <span>A new version is available — reload to get it.</span>
      <button type="button" onClick={() => window.location.reload()} className={button}>
        Reload
      </button>
    </div>
  );
}
