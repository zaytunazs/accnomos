"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";

/** Shared empty/loading/error states. Same look and same words on every page. */

/** A runtime failure, split into the sentence for the user plus machine facts for routing. */
export interface RuntimeErrorInfo {
  status: number | null;
  detail: string;
  ref: string | null;
}

/** Reads the suffix lib/runtime.ts errorDetail appends: "(status 401 · ref abc)" — plus older "-> 401" shapes. */
export function parseRuntimeError(message: string): RuntimeErrorInfo {
  const statusMatch = /(?:\(status|->)\s*(\d{3})/.exec(message);
  const status = statusMatch ? Number(statusMatch[1]) : null;
  const ref = /(?:·|\|) ref ([A-Za-z0-9_-]+)/.exec(message)?.[1] ?? null;
  const detail = message
    .replace(/\s*\(status \d{3}(?:\s*· ref [A-Za-z0-9_-]+)?\)\s*$/, "")
    .replace(/\s*(?:·|\|) ref [A-Za-z0-9_-]+\s*$/, "")
    .trim();
  return { status, detail, ref };
}

/** An expired sign-in: HTTP 401, or an unauthorised message that is not a consent redirect. */
export function isAuthError(message: string): boolean {
  if (parseRuntimeError(message).status === 401) return true;
  return (
    /\bunauthori[sz]ed\b/i.test(message) &&
    !/redirecting for consent/i.test(message)
  );
}

/** A server fault: HTTP 5xx. The runtime logs it under the correlation id. */
export function isServerError(message: string): boolean {
  const status = parseRuntimeError(message).status;
  return status !== null && status >= 500 && status <= 599;
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div aria-live="polite" className={`${card} text-center`}>
      <span
        aria-hidden="true"
        className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-teal-tint"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path
            d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6L10 2.5Z"
            stroke="#0A4F47"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <path
            d="M7 10.2l2.1 2.1L13.2 8"
            stroke="#0A4F47"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <h2 className="mt-3 text-lg font-extrabold tracking-tight">{title}</h2>
      {body ? (
        <p className="mx-auto mt-1 max-w-md text-[15px] leading-7 text-muted">{body}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

const skeletonWidths = ["w-3/4", "w-full", "w-1/2", "w-2/3"];

export function LoadingSkeleton({
  lines = 3,
  label = "Loading…",
}: {
  lines?: number;
  label?: string;
}) {
  return (
    <div role="status" className={card}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="flex flex-col gap-3">
        {Array.from({ length: lines }).map((_, i) => (
          <span
            key={i}
            className={`h-4 animate-pulse rounded-full bg-ground ${skeletonWidths[i % skeletonWidths.length]}`}
          />
        ))}
      </div>
    </div>
  );
}

export function ErrorNote({
  title = "Something went wrong",
  body,
  action,
}: {
  title?: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-warn-border bg-warn-bg p-4 sm:p-5"
    >
      <p className="text-[15px] font-extrabold text-warn-ink">{title}</p>
      {body ? (
        <p className="mt-1 text-[14px] leading-6 text-warn-ink">{body}</p>
      ) : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

/** Every page shows this one strip when the runtime answers 401: sign in again, not a raw message. */
export function AuthErrorStrip() {
  const path = usePathname() ?? "/";
  const href =
    path === "/connect" || path.startsWith("/connect/")
      ? "/connect"
      : `/connect?next=${encodeURIComponent(path)}`;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-warn-border bg-warn-bg px-4 py-3"
    >
      <p className="min-w-0 flex-1 text-[15px] font-bold text-warn-ink">
        Your sign-in has expired. Sign in again to continue — nothing is lost.
      </p>
      <Link
        href={href}
        className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
      >
        Sign in again
      </Link>
    </div>
  );
}

/** A 5xx from the runtime: the sentence plus its correlation id, with copy, so support can find it. */
export function ServerErrorNote({ message }: { message: string }) {
  const info = parseRuntimeError(message);
  const [copied, setCopied] = useState(false);
  const quote = `Accnomos error (status ${info.status ?? "unknown"}): ${info.detail}${info.ref ? ` [ref ${info.ref}]` : ""}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(quote);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div role="alert" className="rounded-2xl border border-warn-border bg-warn-bg p-4 sm:p-5">
      <p className="text-[15px] font-extrabold text-warn-ink">Something went wrong on our side</p>
      <p className="mt-1 text-[14px] leading-6 text-warn-ink">{info.detail || message}</p>
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] text-warn-ink">
        <span>
          Quote this reference:{" "}
          <code className="rounded bg-white px-1.5 py-0.5 font-mono text-[13px] font-bold">
            {info.ref ?? "no reference given"}
          </code>
        </span>
        <button
          type="button"
          onClick={copy}
          className="shrink-0 whitespace-nowrap rounded-lg border border-warn-border bg-white px-3 py-1 text-[13px] font-bold"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </p>
    </div>
  );
}

/** Route a runtime failure to the one shared strip: 401 signs in again, 5xx quotes its reference. */
export function RuntimeErrorNote({ message, title }: { message: string; title?: string }) {
  if (isAuthError(message)) return <AuthErrorStrip />;
  if (isServerError(message)) return <ServerErrorNote message={message} />;
  return <ErrorNote title={title ?? "Couldn't finish that"} body={parseRuntimeError(message).detail} />;
}

/** The reader (runtime) service is unreachable from this browser. */
export function ReaderErrorNote({ detail }: { detail?: string }) {
  return (
    <ErrorNote
      title="Reader service isn't answering — check Settings › Reader address"
      body={detail ?? "Try again in a moment."}
      action={
        <Link
          href="/settings"
          className="inline-block whitespace-nowrap text-[14px] font-bold text-warn-ink underline underline-offset-2"
        >
          Open Settings
        </Link>
      }
    />
  );
}

/** Fetch failures mean the reader service is down; anything else is shown as-is. */
export function isReaderError(message: string): boolean {
  return /failed to fetch|networkerror|network error|econn|refused|load failed|not answering|timed out/i.test(
    message,
  );
}
