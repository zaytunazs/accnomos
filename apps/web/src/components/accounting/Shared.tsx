"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import SignInCta from "@/components/SignInCta";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";

/** The accounting tools, one link each. The signed-in top menu is being redesigned elsewhere; until then this row
 *  is how the pages find each other (listed in REVIEW.md). */
export const TOOLS = [
  { href: "/accounting/chart", label: "Chart of accounts" },
  { href: "/accounting/journals", label: "Manual journals" },
  { href: "/accounting/assets", label: "Fixed assets" },
  { href: "/accounting/recode", label: "Find and recode" },
  { href: "/accounting/tracking", label: "Tracking" },
  { href: "/reports/budgets", label: "Budgets" },
  { href: "/reports/cashflow", label: "Cash flow" },
];

export function ToolsNav() {
  const path = usePathname();
  return (
    <nav aria-label="Accounting tools" className="-mx-1 overflow-x-auto print:hidden">
      <ul className="flex gap-1.5 px-1 pb-1">
        {TOOLS.map((t) => {
          const here = path === t.href || path === `${t.href}/`;
          return (
            <li key={t.href} className="shrink-0">
              <Link
                href={t.href}
                aria-current={here ? "page" : undefined}
                className={`inline-flex min-h-11 items-center rounded-full border px-3.5 text-[14px] font-bold ${
                  here ? "border-teal bg-teal text-white" : "border-border bg-white text-ink hover:border-teal"
                }`}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function ToolPage({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div data-print-page className="flex min-w-0 flex-col gap-5">
      <ToolsNav />
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold tracking-tight">{title}</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">{description}</p>
      </div>
      {children}
    </div>
  );
}

export const input = "h-11 w-full min-w-0 rounded-xl border border-border bg-white px-3 text-[15px]";
export const button = "inline-flex h-11 items-center justify-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
export const quiet = "inline-flex h-11 items-center justify-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold hover:border-teal disabled:opacity-60";
export const small = "inline-flex min-h-11 items-center rounded-lg border border-border bg-white px-3 text-[14px] font-bold hover:border-teal disabled:opacity-60";
export const card = "min-w-0 rounded-2xl border border-border bg-white p-4 sm:p-5";
export const th = "py-2 pr-3 text-[13px] font-bold text-muted";
export const td = "py-2 pr-3 align-top";

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-[13px] font-bold text-muted">
      {label}
      {children}
      {hint && <span className="text-[12px] font-normal">{hint}</span>}
    </label>
  );
}

/** Notes after an action: `note` is a status line, `error` a runtime refusal or failure. */
export function Notes({ note, error }: { note: string | null; error: string | null }) {
  return (
    <>
      {note && (
        <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">
          {note}
        </p>
      )}
      {error && (
        <div role="alert">
          <RuntimeErrorNote message={error} />
        </div>
      )}
    </>
  );
}

/** Load something for the signed-in account; `act` runs a change, then loads again. */
export function useLoad<T>(load: (a: AccountInfo) => Promise<T>) {
  const account = useAccount();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!account) return;
    try {
      setData(await load(account));
    } catch (e) {
      setError(errorText(e));
    }
  }, [account, load]);

  useEffect(() => {
    if (account) queueMicrotask(() => void reload());
  }, [account, reload]);

  async function act<R>(key: string, fn: (a: AccountInfo) => Promise<R>, done?: (r: R) => string | null): Promise<R | null> {
    if (!account) return null;
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      const r = await fn(account);
      const msg = done ? done(r) : null;
      if (msg) setNote(msg);
      await reload();
      return r;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  }

  return { account, data, setData, error, setError, note, setNote, busy, act, reload };
}

/** Signed out: what the page does, and the sign-in button. Loading: the skeleton. */
export function Gate({
  account,
  ready,
  what,
  children,
}: {
  account: AccountInfo | null | undefined;
  ready: boolean;
  what: string;
  children: ReactNode;
}) {
  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading…" />;
  if (account === null)
    return (
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-white p-5 text-[15px] leading-7 text-muted">
        <SignInCta />
        <span>{what}</span>
      </p>
    );
  if (!ready) return <LoadingSkeleton lines={3} label="Loading…" />;
  return <>{children}</>;
}

/** A table that scrolls sideways inside its card on a narrow phone, never the page. `relative`: the table's sr-only
 *  caption is absolutely positioned and would otherwise escape the clipping and widen the page (docs/reviews/ci). */
export function Scroll({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="relative max-w-full overflow-x-auto" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
