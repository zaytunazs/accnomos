"use client";

import Link from "next/link";
import ExplainMore from "@/components/ExplainMore";
import type { RtDashboard } from "@/lib/runtime";
import { tiles as sampleTiles, type Tile } from "@/lib/sample-home";
import { pounds, shortDate, Skeleton, UNKNOWN, useHome } from "./HomeData";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function cashTile(cash: RtDashboard["cash"]): Tile {
  const label = "Cash in bank";
  if (!cash) return { label, value: UNKNOWN, sub: "Could not read the bank statements" };
  if (cash.balance_pence === null) return { label, value: UNKNOWN, sub: "Import a statement and match a line", href: "/bank" };
  const reconciled = cash.reconciled_to ? ` · reconciled to ${shortDate(cash.reconciled_to)}` : "";
  return { label, value: pounds(cash.balance_pence), sub: `Balance on ${shortDate(cash.as_of)}${reconciled}` };
}

function owedToYouTile(owed: RtDashboard["owed_to_you"]): Tile {
  const label = "Owed to you";
  if (!owed) return { label, value: UNKNOWN, sub: "Could not read the ledger" };
  if (owed.overdue)
    return {
      label, value: pounds(owed.total_pence), tone: "amber", href: "/invoices",
      sub: `${plural(owed.overdue, "invoice")} overdue, ${plural(owed.most_overdue_days ?? 0, "day")} at most`,
    };
  return { label, value: pounds(owed.total_pence), sub: owed.documents ? `${plural(owed.documents, "unpaid sale")}` : "Nothing unpaid" };
}

function owedByYouTile(owed: RtDashboard["owed_by_you"]): Tile {
  const label = "Owed by you";
  if (!owed) return { label, value: UNKNOWN, sub: "Could not read the ledger" };
  const oldest = owed.oldest_days !== null ? `, oldest ${plural(owed.oldest_days, "day")}` : "";
  return { label, value: pounds(owed.total_pence), sub: owed.documents ? `${plural(owed.documents, "unpaid bill")}${oldest}` : "Nothing unpaid" };
}

function vatTile(vat: RtDashboard["vat"], annual: boolean): Tile {
  if (annual) return { label: "VAT estimate", value: UNKNOWN, sub: "Annual returns are not estimated yet" };
  if (!vat) return { label: "VAT estimate", value: UNKNOWN, sub: "Could not work out the VAT period" };
  const next = vat.due ?? vat.current; // the return to file next
  const amount = `£${Math.round(Number(next.box5)).toLocaleString("en-GB")}`;
  const what = { pay: "To pay by", reclaim: "To reclaim, return due", nil: "Nothing to pay, return due" }[next.box5_direction];
  const sub = `${what} ${shortDate(next.deadline)}${
    next === vat.current ? " · so far" : ""}`;
  return { label: `VAT estimate · ${next.label}`, value: next.box5_direction === "nil" ? "£0" : amount, sub, href: "/vat" };
}

function attentionTile(a: RtDashboard["attention"]): Tile {
  const label = "Needs attention";
  if (!a) return { label, value: UNKNOWN, sub: "Could not read your books" };
  if (!a.total) return { label, value: "0", sub: "Nothing waiting" };
  const parts = [
    a.proposed && `${a.proposed} to approve`,
    a.needs_a_look && `${a.needs_a_look} to look at`,
    a.unmatched_bank_lines && plural(a.unmatched_bank_lines, "bank line"),
    a.overdue_invoices && `${a.overdue_invoices} overdue`,
  ].filter(Boolean);
  const href = a.proposed || a.needs_a_look ? "/review" : a.unmatched_bank_lines ? "/bank" : "/invoices";
  return { label, value: String(a.total), sub: `${parts.join(" · ")} →`, tone: "warn", href };
}

function liveTiles(d: RtDashboard, annualVat: boolean): Tile[] {
  return [cashTile(d.cash), owedToYouTile(d.owed_to_you), owedByYouTile(d.owed_by_you), vatTile(d.vat, annualVat),
    attentionTile(d.attention)];
}

const LABELS = ["Cash in bank", "Owed to you", "Owed by you", "VAT estimate", "Needs attention"];

/** Home tiles: GET /books/dashboard when signed in, the sample when signed out. */
export default function Tiles() {
  const home = useHome();
  const tiles: Tile[] | null =
    home.mode === "sample" ? sampleTiles
    : home.mode === "live" ? liveTiles(home.data, home.annualVat)
    : home.mode === "error" ? LABELS.map((label) => ({ label, value: UNKNOWN, sub: "Could not reach your books" }))
    : null;

  return (
    <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[900px]:grid-cols-3 min-[1180px]:grid-cols-5">
      {tiles === null
        ? LABELS.map((label) => (
            <div key={label} className="rounded-2xl border border-border bg-white p-4" aria-busy="true">
              <p className="text-sm font-semibold text-muted">{label}</p>
              <Skeleton className="mt-2 h-7 w-24" />
              <Skeleton className="mt-2 h-4 w-36" />
            </div>
          ))
        : tiles.map((tile) => <TileCard key={tile.label} tile={tile} />)}
    </div>
  );
}

const TILE_HELP: Record<string, { title: string; anchor: string; text: string }> = {
  "Cash in bank": { title: "What Cash in bank means", anchor: "bank", text: "The balance from your imported statements, worked out by code. Import a statement and match a line to see it here." },
  "Owed to you": { title: "What Owed to you means", anchor: "invoices", text: "Unpaid sales from your ledger, worked out by code. A matched bank line counts as full payment." },
  "Owed by you": { title: "What Owed by you means", anchor: "bank", text: "Unpaid purchase bills from your ledger, worked out by code." },
  "VAT estimate": { title: "What the VAT estimate means", anchor: "vat-periods", text: "Box 5 so far from approved entries, worked out by code for your VAT period. Annual returns are not estimated yet." },
  "Needs attention": { title: "What Needs attention means", anchor: "receipts", text: "Proposals to approve, files needing a look, unmatched bank lines and overdue invoices. Nothing here posts by itself." },
};

function TileCard({ tile }: { tile: Tile }) {
  const warn = tile.tone === "warn";
  const help = TILE_HELP[tile.label.split(" · ")[0]] ?? TILE_HELP[tile.label];
  const subClass = warn
    ? "text-sm font-bold text-warn-ink underline"
    : `text-[13px] font-semibold ${tile.tone === "amber" ? "text-amber" : "text-muted"}`;
  return (
    <div role="group" aria-label={tile.label} className={`rounded-2xl border p-4 ${warn ? "border-warn-border bg-warn-bg" : "border-border bg-white"}`}>
      <div className="flex items-center justify-between gap-2">
        <p className={`text-sm font-semibold ${warn ? "text-warn-ink" : "text-muted"}`}>{tile.label}</p>
        {help && (
          <ExplainMore title={help.title} anchor={help.anchor}>
            {help.text}
          </ExplainMore>
        )}
      </div>
      <p className={`mt-1 text-2xl font-extrabold tracking-tight ${warn ? "text-warn-ink" : "text-ink"}`}>{tile.value}</p>
      {tile.href ? (
        <Link href={tile.href} className={`mt-1 inline-block hover:underline ${subClass}`}>
          {tile.sub}
        </Link>
      ) : (
        <p className={`mt-1 ${subClass}`}>{tile.sub}</p>
      )}
    </div>
  );
}
