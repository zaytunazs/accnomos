import Link from "next/link";
import type { ReactNode } from "react";

const card = "rounded-2xl border border-border bg-white p-5 sm:p-6";

/** Shared empty/loading/error states. Same look and same words on every page. */

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
    <div className={`${card} text-center`}>
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
