"use client";

import Link from "next/link";
import { usePowerGridOn } from "@/lib/power-grid";

/** Reports: the ledger explorer link, shown only while the Power grid add-on is on (Settings › Business). */
export default function PowerGridLink() {
  const on = usePowerGridOn();
  if (!on) return null;
  return (
    <p className="text-[15px] print:hidden">
      <Link href="/reports/ledger-grid" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
        Ledger explorer
      </Link>
      <span className="text-muted"> · every journal line in a grid: type what you want to see, sort, filter, total and export</span>
    </p>
  );
}
