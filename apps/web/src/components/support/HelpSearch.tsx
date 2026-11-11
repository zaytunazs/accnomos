"use client";

import Link from "next/link";
import { useState } from "react";
import { HELP_CATEGORIES, searchHelp } from "@/lib/help";

/** The help centre's article list with a search box (matches title, summary, keywords and steps). */
export default function HelpSearch() {
  const [q, setQ] = useState("");
  const found = searchHelp(q);
  return (
    <div className="mt-6 flex flex-col gap-6">
      <label className="block">
        <span className="sr-only">Search the help centre</span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search: VAT return, PayPal dispute, bank feed…"
          className="h-12 w-full rounded-xl border border-border bg-white px-4 text-[15px]"
        />
      </label>
      {found.length === 0 && (
        <p className="text-[15px] text-muted" role="status">
          No article matches that. Try fewer words, or <Link href="/support" className="font-bold text-teal-dark underline">ask the support assistant</Link>.
        </p>
      )}
      {HELP_CATEGORIES.map((c) => {
        const list = found.filter((a) => a.category === c.id);
        if (!list.length) return null;
        return (
          <section key={c.id} aria-labelledby={`help-cat-${c.id}`}>
            <h2 id={`help-cat-${c.id}`} className="text-[17px] font-extrabold">
              {c.title}
            </h2>
            <ul className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
              {list.map((a) => (
                <li key={a.id}>
                  <Link href={`/help/${a.id}`} className="block h-full rounded-2xl border border-border bg-white p-4 hover:bg-ground">
                    <span className="block text-[15px] font-extrabold text-teal-dark">{a.title}</span>
                    <span className="mt-1 block text-sm text-ink">{a.summary}</span>
                    <span className="mt-2 block text-[12px] font-bold uppercase tracking-wide text-muted">
                      {a.platforms.map((p) => (p === "android" ? "Android" : "Web")).join(" · ")} · {a.steps.length} steps
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
