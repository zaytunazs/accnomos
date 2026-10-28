"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { demoAlive, isDemo, leaveDemo, startDemo } from "@/lib/demo";

/** Reset demo: a fresh copy of the sample books (the runtime drops the old one), then Home. */
export async function resetDemo(): Promise<void> {
  await startDemo();
  // A full load, not router.push: the fake sign-in (getMsal) and every page's data must start again.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/");
}

function useDemo(dep?: unknown): boolean {
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    queueMicrotask(() => setDemo(isDemo()));
  }, [dep]);
  return demo;
}

const linkBtn = "font-bold text-ground underline underline-offset-2 hover:no-underline disabled:opacity-60";

/**
 * The banner on every page of a demo sandbox, with Reset demo and the way out to real sign-in. Says so when the
 * session has ended (2 hours idle) instead of letting every page fail.
 */
export default function DemoBar() {
  const path = usePathname() ?? "/";
  const demo = useDemo(path);
  const [ended, setEnded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!demo) return;
    let stale = false;
    demoAlive().then((alive) => !stale && setEnded(alive === false));
    return () => {
      stale = true;
    };
  }, [demo, path]);

  if (!demo) return null;

  async function reset() {
    setBusy(true);
    setError(null);
    try {
      await resetDemo();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <aside aria-label="Demo sandbox">
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-ink px-4 py-2 text-center text-[13px] text-ground">
        {ended ? (
          <span className="font-bold">This demo has ended (demos reset after 2 hours). Start a new one to carry on.</span>
        ) : (
          <span className="font-bold">Demo sandbox with sample data — changes reset after 2 hours.</span>
        )}
        <button type="button" onClick={() => void leaveDemo("/connect")} className={linkBtn}>
          Set up your own books →
        </button>
        <span aria-hidden="true">·</span>
        <button type="button" onClick={reset} disabled={busy} className={linkBtn}>
          {busy ? "Resetting…" : ended ? "Start a new demo" : "Reset demo"}
        </button>
        {error && (
          <span role="alert" className="w-full font-semibold">
            {error}
          </span>
        )}
      </div>
    </aside>
  );
}

/** Reset demo / Leave demo in the sidebar menu, and where the demo's books live. */
export function DemoMenu() {
  const demo = useDemo();
  const [busy, setBusy] = useState(false);
  if (!demo) return null;
  return (
    <div className="flex flex-col gap-1 rounded-2xl border border-border p-3 text-sm">
      <p className="font-bold">Demo sandbox</p>
      <p className="text-muted">These sample books live in memory on the server and reset after 2 hours.</p>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await resetDemo();
          } catch {
            setBusy(false);
          }
        }}
        className="mt-1 h-10 rounded-xl border border-border bg-white px-3 text-left font-bold text-teal-dark hover:bg-ground"
      >
        {busy ? "Resetting…" : "Reset demo"}
      </button>
      <button
        type="button"
        onClick={() => void leaveDemo("/connect")}
        className="h-10 rounded-xl px-3 text-left font-bold text-teal-dark hover:bg-ground"
      >
        Leave demo
      </button>
    </div>
  );
}

/** Children only outside a demo (e.g. "Your books live in OneDrive", which a demo's books don't). */
export function NotInDemo({ children }: { children: React.ReactNode }) {
  const demo = useDemo();
  return demo ? null : <>{children}</>;
}
