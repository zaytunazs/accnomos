"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import Explain from "@/components/Explain";

/** Plain-English feed for each box: what counts towards it, in the ledger's terms. */
const FEEDS: Record<number, string> = {
  1: "VAT charged on your sales in this period — sales invoices and takings with VAT code S count; anything outside the scope of UK VAT (code O) is left out.",
  2: "VAT due on goods you acquired from Northern Ireland and the EU. £0 when you only trade in Great Britain.",
  3: "Box 1 plus Box 2, added by code — never typed in.",
  4: "VAT you reclaim on purchases in this period — the receipts and bills you approved with VAT on them.",
  5: "What you owe HMRC: Box 3 minus Box 4, worked out by code. Positive means pay, negative means reclaim.",
  6: "Total sales excluding VAT, in whole pounds (rounded down).",
  7: "Total purchases excluding VAT, in whole pounds (rounded down).",
  8: "Goods you supplied to Northern Ireland and the EU, excluding VAT. £0 when you only trade in Great Britain.",
  9: "Goods you acquired from Northern Ireland and the EU, excluding VAT. £0 when you only trade in Great Britain.",
};

/**
 * The shared "?" drawer for one VAT box: what feeds it in plain English, which entries
 * (count, linked to Review; originals in Files), and optional extra copy such as Box 5's
 * pay/reclaim wording with its due date.
 */
export default function BoxExplain({
  box,
  label,
  entries,
  extra,
}: {
  box: number;
  label: string;
  entries: number | null;
  extra?: ReactNode;
}) {
  return (
    <Explain title={`Box ${box} · ${label}`}>
      <p>{FEEDS[box] ?? "Worked out by code from the entries you approved."}</p>
      {entries ? (
        <p>
          <Link
            href="/review"
            className="font-bold text-teal underline underline-offset-2 hover:text-teal-dark"
          >
            {entries} approved {entries === 1 ? "entry feeds" : "entries feed"} Box {box} — see them on Review
          </Link>
          . The original receipts and invoices are in{" "}
          <Link href="/files" className="font-bold text-teal underline underline-offset-2 hover:text-teal-dark">
            Files
          </Link>
          .
        </p>
      ) : (
        <p>
          No entries feed Box {box} in this period. If that looks wrong, the entries are on{" "}
          <Link href="/review" className="font-bold text-teal underline underline-offset-2 hover:text-teal-dark">
            Review
          </Link>{" "}
          and the originals in{" "}
          <Link href="/files" className="font-bold text-teal underline underline-offset-2 hover:text-teal-dark">
            Files
          </Link>
          .
        </p>
      )}
      {extra ? <p>{extra}</p> : null}
    </Explain>
  );
}
