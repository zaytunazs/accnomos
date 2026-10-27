"use client";

import Link from "next/link";
import { useState } from "react";

/** Copy to the clipboard, falling back to a temporary textarea (older browsers, non-secure contexts). */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch {
      return false;
    }
  }
}

/**
 * The shared problem page in the app's style: one card, the reference when the
 * trouble came from the runtime, and Back to Home plus Copy details (error.tsx
 * adds Try again via onRetry). The page address and time are added at copy time.
 */
export function ProblemCard({
  title,
  body,
  reference,
  detailLines,
  onRetry,
}: {
  title: string;
  body: string;
  reference?: string | null;
  detailLines?: string[];
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    const lines = [title, body];
    if (reference) lines.push(`Reference: ${reference}`);
    for (const line of detailLines ?? []) lines.push(line);
    lines.push(`Page: ${window.location.href}`, `Time: ${new Date().toISOString()}`);
    setCopied(await copyText(lines.join("\n")));
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-5 sm:p-6">
      <h1 className="text-3xl font-extrabold tracking-tight">{title}</h1>
      <p className="mt-1 text-[15px] leading-7 text-muted">{body}</p>
      {reference ? (
        <p className="mt-3 text-[14px] text-muted">
          Quote this reference:{" "}
          <code className="rounded bg-ground px-1.5 py-0.5 font-mono text-[13px] font-bold text-ink">
            {reference}
          </code>
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="h-11 rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark"
          >
            Try again
          </button>
        ) : null}
        <Link
          href="/"
          className="inline-flex h-11 items-center rounded-xl border border-border bg-white px-4 text-[15px] font-bold text-teal-dark hover:bg-ground"
        >
          Back to Home
        </Link>
        <button
          type="button"
          onClick={copy}
          className="h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold text-teal-dark hover:bg-ground"
        >
          {copied ? "Copied" : "Copy details"}
        </button>
      </div>
    </div>
  );
}
