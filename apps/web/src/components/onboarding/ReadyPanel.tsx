"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadBusiness } from "@/lib/business";

const NEXT_STEPS = [
  "Drop receipts into 00 Inbox or snap them in the app",
  "Accnomos reads them with Meta AI and proposes entries",
  "You approve; code posts and keeps the VAT return",
];

export default function ReadyPanel() {
  const [businessName, setBusinessName] = useState<string | null>(null);

  useEffect(() => {
    const saved = loadBusiness();
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => setBusinessName(saved?.name.trim() ? saved.name.trim() : null));
  }, []);

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-2xl border border-teal bg-teal-tint p-4">
        <div className="font-extrabold text-teal-dark">Your folder is ready</div>
        <p className="mt-1 text-sm text-ink">OneDrive › Apps › Accnomos</p>
      </div>

      <p className="text-[15px] font-bold text-ink">
        {businessName ? `${businessName} is set up.` : "You're set up."}
      </p>

      <ol className="space-y-2">
        {NEXT_STEPS.map((step, i) => (
          <li
            key={step}
            className="flex items-start gap-3 rounded-2xl border border-border bg-white p-4 text-[15px] text-ink"
          >
            <span
              aria-hidden="true"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-tint text-[13px] font-extrabold text-teal-dark"
            >
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap gap-3">
        <Link
          href="/files"
          className="inline-flex h-12 items-center rounded-xl border border-teal bg-white px-5 text-[15px] font-bold text-teal-dark"
        >
          See your files
        </Link>
        <Link
          href="/"
          className="inline-flex h-12 flex-1 items-center justify-center rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white hover:bg-teal-dark"
        >
          Go to Home
        </Link>
      </div>
    </div>
  );
}
