"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

export const CONNECT_STEPS = [
  { n: 1, label: "Sign in", href: "/connect" },
  { n: 2, label: "Choose AI", href: "/connect/ai" },
  { n: 3, label: "Your business", href: "/connect/business" },
  { n: 4, label: "Ready", href: "/connect/ready" },
] as const;

/**
 * Carry ?next= through the wizard so step 4 can return there afterwards.
 * Only same-site paths; anything else is dropped.
 */
export function withNext(href: string, next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return href;
  return `${href}?next=${encodeURIComponent(next)}`;
}

/**
 * The validated ?next= value, or null when absent or not a same-site path.
 * Read from window.location on the client (no useSearchParams), so this hook
 * works on any page — including ones reused outside the wizard, like Settings —
 * without needing a Suspense boundary in a static export.
 */
export function useNextParam(): string | null {
  const [next, setNext] = useState<string | null>(null);
  useEffect(() => {
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      const raw = new URLSearchParams(window.location.search).get("next");
      setNext(raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : null);
    });
  }, []);
  return next;
}

function StepsList({ current, next }: { current: number; next: string | null }) {
  return (
    <nav aria-label="Connect progress">
      <ol className="grid grid-cols-4 gap-1.5">
        {CONNECT_STEPS.map((s) => {
          const isCurrent = s.n === current;
          return (
            <li key={s.n}>
              <Link
                href={withNext(s.href, next)}
                aria-current={isCurrent ? "step" : undefined}
                className={`flex flex-col items-center gap-0.5 rounded-xl border px-1 py-2 text-center ${
                  isCurrent
                    ? "border-teal bg-teal-tint text-teal-dark"
                    : "border-border bg-white text-muted hover:text-ink"
                }`}
              >
                <span aria-hidden="true" className="text-[13px] font-extrabold">
                  {s.n < current ? "✓" : s.n}
                </span>
                <span className={`text-[11px] leading-tight ${isCurrent ? "font-extrabold" : "font-bold"}`}>
                  {s.label}
                  {isCurrent && <span className="sr-only"> (current step)</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      <div
        role="progressbar"
        aria-label={`Step ${current} of ${CONNECT_STEPS.length}`}
        aria-valuemin={1}
        aria-valuemax={CONNECT_STEPS.length}
        aria-valuenow={current}
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-ground"
      >
        <div
          aria-hidden="true"
          className="h-1.5 rounded-full bg-teal transition-all"
          style={{ width: `${Math.round((current / CONNECT_STEPS.length) * 100)}%` }}
        />
      </div>
    </nav>
  );
}

function StepsWithNext({ current }: { current: number }) {
  return <StepsList current={current} next={useNextParam()} />;
}

/** The four-step progress bar shared by every /connect page. Current step carries aria-current. */
export default function ConnectSteps({ current }: { current: 1 | 2 | 3 | 4 }) {
  return <StepsWithNext current={current} />;
}
