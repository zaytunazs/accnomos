"use client";

import { useEffect, useState, type ReactNode } from "react";
import { isDemo, startDemo } from "@/lib/demo";
import { runtimeHealth } from "@/lib/runtime";

let healthOnce: Promise<boolean | null> | null = null;

/** Whether this runtime offers demo sandboxes (GET /health `demo`); null until known or when it can't say. */
export function useDemoAvailable(): boolean | null {
  const [available, setAvailable] = useState<boolean | null>(null);
  useEffect(() => {
    let stale = false;
    healthOnce ??= runtimeHealth().then((h) => (h === null ? null : h.demo?.enabled === true));
    void healthOnce.then((a) => !stale && setAvailable(a));
    return () => {
      stale = true;
    };
  }, []);
  return available;
}

/** Its children only when demos can start here, and never inside one. */
export function IfDemoAvailable({ children }: { children: ReactNode }) {
  const available = useDemoAvailable();
  const [inDemo, setInDemo] = useState(true);
  useEffect(() => queueMicrotask(() => setInDemo(isDemo())), []);
  return available === true && !inDemo ? <>{children}</> : null;
}

/**
 * "Try the demo — no sign-in": starts a demo sandbox (lib/demo.ts) and opens `next` in it. Hidden when the runtime
 * says demos are off (DEMO_MODE unset), unless `always` (the /judges page explains instead).
 */
export default function TryDemo({
  next = "/",
  label = "Try the demo — no sign-in",
  variant = "primary",
  always = false,
}: {
  next?: string;
  label?: string;
  variant?: "primary" | "secondary";
  always?: boolean;
}) {
  const available = useDemoAvailable();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (available !== true && !always) return null;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await startDemo();
      window.location.assign(next); // a full load, so every page picks the demo session up
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const cls =
    variant === "primary"
      ? "whitespace-nowrap rounded-xl bg-ink px-4 py-2.5 text-sm font-bold text-ground hover:bg-teal-dark disabled:opacity-60"
      : "whitespace-nowrap rounded-xl border border-ink bg-white px-4 py-2.5 text-sm font-bold text-ink hover:bg-ground disabled:opacity-60";
  return (
    <span className="inline-flex flex-col gap-1">
      <button type="button" onClick={start} disabled={busy || available === false} className={cls}>
        {busy ? "Preparing the sample books…" : label}
      </button>
      {available === false && always && (
        <span className="text-sm text-muted">The demo sandbox isn&apos;t switched on for this server.</span>
      )}
      {error && (
        <span role="alert" className="text-sm font-semibold text-warn-ink">
          {error}
        </span>
      )}
    </span>
  );
}
