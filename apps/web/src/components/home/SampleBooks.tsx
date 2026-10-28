"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import { postSample, sampleStatus, SampleRefused, type RtSampleStatus } from "@/lib/runtime";
import { useHome } from "./HomeData";

export const SAMPLE_LABEL = "SAMPLE — FICTIONAL COMPANY";
const POLL_MS = 3000; // well inside the runtime's per-address budget (60 a minute)
/** Hand the runtime a fresh Graph token this often while it loads (a token lasts about an hour). */
const FRESH_TOKEN_MS = 4 * 60 * 1000;

/**
 * "Load sample books": only while the Accnomos folder is empty (GET /books/sample says `empty`), or while loading
 * runs or has stopped. Polls the status; every few minutes, and whenever the runtime says it needs one, it POSTs
 * again so the background job gets a fresh token. Done: reloads into Home, which then shows the SAMPLE banner.
 */
export default function SampleBooks({ account, place }: { account: AccountInfo; place: "home" | "connect" }) {
  const [status, setStatus] = useState<RtSampleStatus | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const lastPost = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    let live = true;
    sampleStatus(account)
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus(null)); // the runtime unreachable: Home says so elsewhere
    return () => {
      live = false;
    };
  }, [account]);

  const post = useCallback(
    async (carryOn: boolean) => {
      lastPost.current = Date.now();
      try {
        setStatus(await postSample(account, carryOn));
        setRefused(null);
      } catch (e) {
        setRefused(e instanceof SampleRefused ? e.message : "Couldn't reach Accnomos. Check you're online and try again.");
      }
    },
    [account],
  );

  const running = status?.state === "running" || status?.state === "needs_token";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const s = await sampleStatus(account);
        setStatus(s);
        if (s.state === "done") {
          window.clearInterval(timer);
          // Into Home with the books in it: Home reloads, Connect opens it (Home loads its data on arrival).
          if (place === "home") window.location.reload();
          else router.push("/");
          return;
        }
        if (s.state === "needs_token" || Date.now() - lastPost.current > FRESH_TOKEN_MS) await post(true);
      } catch {
        /* one missed poll: the next one tries again */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, account, post, place, router]);

  async function start() {
    if (busy) return;
    setBusy(true);
    await post(false);
    setBusy(false);
    headingRef.current?.focus(); // the button is gone: keep keyboard focus on the card
  }

  if (status === null) return null;
  if (status.state === "done") return place === "home" ? <SampleBanner status={status} /> : <Loaded />;
  if (status.state === "none" && !status.empty) return null; // the folder has books: never offer to mix them

  const failed = status.state === "failed";
  return (
    <section
      aria-labelledby="sample-books-title"
      className="rounded-2xl border border-teal bg-teal-tint p-4"
      aria-busy={running ? true : undefined}
    >
      <h2 id="sample-books-title" ref={headingRef} tabIndex={-1} className="font-extrabold text-teal-dark outline-none">
        {running ? "Loading sample books…" : "Try it with sample books"}
      </h2>
      {!running && !failed && (
        <p className="mt-1 text-sm leading-relaxed text-ink">
          Loads six months of a fictional joinery business (labelled SAMPLE) into your Accnomos folder. You can delete it
          any time by deleting the folder in OneDrive.
        </p>
      )}
      {(running || failed) && <Progress status={status} />}
      {failed && status.error && (
        <p role="alert" className="mt-2 text-sm font-semibold text-ink">
          {status.error}
        </p>
      )}
      {refused && (
        <p role="alert" className="mt-2 text-sm font-semibold text-ink">
          {refused}
        </p>
      )}
      {!running && (
        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="mt-3 inline-flex h-11 items-center justify-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-dark disabled:opacity-60"
        >
          {failed ? "Carry on loading sample books" : busy ? "Starting…" : "Load sample books"}
        </button>
      )}
    </section>
  );
}

function Progress({ status }: { status: RtSampleStatus }) {
  const pct = status.total ? Math.round((100 * status.done) / status.total) : 0;
  const now = status.state === "needs_token" ? "Waiting for your sign-in to renew…" : (status.step ?? "Starting…");
  return (
    <div className="mt-3">
      <div
        role="progressbar"
        aria-label="Loading sample books"
        aria-valuemin={0}
        aria-valuemax={status.total || 1}
        aria-valuenow={status.done}
        aria-valuetext={`${status.done} of ${status.total} steps done${status.step ? `: ${status.step}` : ""}`}
        className="h-3 w-full overflow-hidden rounded-full bg-white"
      >
        <div className="h-full rounded-full bg-teal transition-[width]" style={{ width: `${pct}%` }} />
      </div>
      <p aria-live="polite" className="mt-2 text-sm text-ink">
        <span className="font-semibold">{now}</span>{" "}
        <span className="text-muted">
          · {status.done} of {status.total} steps
        </span>
      </p>
      {status.steps.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer font-semibold text-teal-dark">All steps</summary>
          <ol className="mt-1 max-h-48 list-decimal space-y-0.5 overflow-y-auto pl-6 text-muted">
            {status.steps.map((name, n) => (
              <li key={n} aria-current={n === status.done ? "step" : undefined} className={n < status.done ? "text-ink" : ""}>
                {name}
                <span className="sr-only">{n < status.done ? " (done)" : n === status.done ? " (now)" : ""}</span>
                {n < status.done && <span aria-hidden="true"> ✓</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
      {status.state === "running" && (
        <p className="mt-2 text-[13px] text-muted">
          Keep this page open; it takes a few minutes. You can come back to it from Home.
        </p>
      )}
    </div>
  );
}

/** Home, once sample books are in the folder: say so plainly on every visit. */
function SampleBanner({ status }: { status: RtSampleStatus }) {
  return (
    <section aria-label="Sample books" className="rounded-2xl border border-border bg-white px-4 py-3">
      <p className="text-[12px] font-extrabold uppercase tracking-wide text-teal-dark">{SAMPLE_LABEL}</p>
      <p className="mt-1 text-sm text-ink">
        These are sample books for {status.business ?? "a made-up company"}, loaded to try Accnomos. Every document in
        them is fictional. To start on your own books, delete the Accnomos folder in OneDrive.
      </p>
    </section>
  );
}

function Loaded() {
  return (
    <section aria-label="Sample books" className="rounded-2xl border border-teal bg-teal-tint p-4">
      <p className="font-extrabold text-teal-dark">Sample books are loaded</p>
      <Link href="/" className="mt-2 inline-block text-sm font-bold text-teal-dark underline">
        Open Home
      </Link>
    </section>
  );
}

/** On Home: the card (or banner) for the signed-in user once the dashboard has loaded. */
export function HomeSampleBooks() {
  const home = useHome();
  if (home.mode !== "live") return null;
  return <SampleBooks account={home.account} place="home" />;
}
