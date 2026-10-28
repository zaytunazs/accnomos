"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getClientContext, onClientContextChange, setClientContext, type ClientContext } from "@/lib/accountant";

/**
 * Shown on every page while an accountant has a client's books open in this tab (lib/accountant.ts): whose books
 * these are, view or edit, and the way back. Nothing here is the accountant's own.
 */
export default function ClientBanner() {
  const router = useRouter();
  const [ctx, setCtx] = useState<ClientContext | null>(null);

  useEffect(() => {
    queueMicrotask(() => setCtx(getClientContext()));
    return onClientContextChange(() => setCtx(getClientContext()));
  }, []);

  if (!ctx) return null;
  return (
    <div role="region" aria-label="Client books" className="border-b border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-ink">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2">
        <p>
          <strong>{ctx.name || "A client"}&apos;s books</strong> ·{" "}
          {ctx.access === "edit" ? "View and edit: changes are recorded under your name" : "View only: nothing can be changed"}
        </p>
        <span className="flex gap-3">
          <Link href="/accountant" className="font-bold underline">
            Queries
          </Link>
          <button
            type="button"
            onClick={() => {
              setClientContext(null);
              router.push("/accountant");
            }}
            className="font-bold underline"
          >
            Back to your clients
          </button>
        </span>
      </div>
    </div>
  );
}
