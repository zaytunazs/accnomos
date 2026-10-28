"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { personalOn, setPersonalOn } from "@/lib/personal";

/** Settings › Business › Show personal finances: adds the Personal page to the menu. Off by default. */
export default function PersonalFinanceSetting({ card, heading }: { card: string; heading: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    queueMicrotask(() => setOn(personalOn()));
  }, []);

  function toggle() {
    setPersonalOn(!on);
    setOn(!on);
  }

  return (
    <section aria-labelledby="settings-personal" className={card}>
      <h2 id="settings-personal" className={heading}>
        Personal finances
      </h2>
      <p className="mt-1 text-sm text-muted">
        Household budgets, bills and savings goals from the bank statements you import. No investment advice and no
        credit score; anything estimated is labelled.
      </p>
      <label className="mt-3 flex min-h-11 items-center gap-3 text-[15px] font-bold text-ink">
        <input type="checkbox" checked={on} onChange={toggle} className="h-5 w-5 accent-teal" />
        Show personal finances
      </label>
      {on && (
        <Link href="/personal" className="mt-2 inline-block text-sm font-bold text-teal-dark">
          Open Personal
        </Link>
      )}
    </section>
  );
}
