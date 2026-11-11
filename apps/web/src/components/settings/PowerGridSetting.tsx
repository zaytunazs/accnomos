"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { powerGridOn, setPowerGridOn } from "@/lib/power-grid";

/** Settings › Business › Power grid: an optional add-on, off by default (on this device only). On, the PayPal panel's
 *  waiting transactions open in a review grid on wide screens, and Reports gains the ledger explorer. */
export default function PowerGridSetting({ card, heading }: { card: string; heading: string }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    queueMicrotask(() => setOn(powerGridOn()));
  }, []);

  function toggle() {
    setPowerGridOn(!on);
    setOn(!on);
  }

  return (
    <section id="settings-power-grid" aria-labelledby="settings-power-grid-title" className={`${card} scroll-mt-4`}>
      <h2 id="settings-power-grid-title" className={heading}>
        Power grid
      </h2>
      <p className="mt-1 text-sm text-muted">
        Spreadsheet-style grids for bulk work: tick several PayPal transactions and approve them in one go, sort and filter
        every column, see totals and export CSV, and explore your ledger by typing what you want to see. Wide screens only;
        phones keep the usual lists. Filters only change what is shown, never your books.
      </p>
      <label className="mt-3 flex min-h-11 items-center gap-3 text-[15px] font-bold text-ink">
        <input type="checkbox" checked={on} onChange={toggle} className="h-5 w-5 accent-teal" />
        Use the power grid
      </label>
      {on && (
        <Link href="/reports/ledger-grid" className="mt-2 inline-block text-sm font-bold text-teal-dark">
          Open the ledger explorer
        </Link>
      )}
    </section>
  );
}
