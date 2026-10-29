"use client";

import Link from "next/link";
import { scanCounts, useScanJobs } from "@/lib/scan-jobs";

/**
 * The top bar's count of background scans (lib/scan-jobs.ts): "Reading 2" while files are being read, "1 to confirm"
 * when the AI has said what a file is and is waiting for the user. Nothing shows when no scan is under way.
 */
export default function ScanBadge() {
  const { working, toConfirm } = scanCounts(useScanJobs());
  if (!working && !toConfirm) return null;
  const label = working ? `Reading ${working}` : `${toConfirm} to confirm`;
  const long = [
    working ? `${working} file${working === 1 ? "" : "s"} being read` : "",
    toConfirm ? `${toConfirm} waiting for you to confirm the type` : "",
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <Link
      href="/review"
      title={long}
      aria-label={`Scans: ${long}`}
      data-scan-badge=""
      className="mr-1 flex h-9 items-center gap-1.5 whitespace-nowrap rounded-full bg-teal-tint px-3 text-[13px] font-bold text-teal-dark hover:bg-ground"
    >
      {working ? <span aria-hidden="true" className="h-2 w-2 animate-pulse rounded-full bg-teal" /> : null}
      {label}
    </Link>
  );
}
