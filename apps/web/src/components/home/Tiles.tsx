"use client";

import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import ExplainMore from "@/components/ExplainMore";
import { isTileError, type RtDashboard } from "@/lib/runtime";
import { tiles as sampleTiles, type Tile } from "@/lib/sample-home";
import Greeting from "./Greeting";
import { pounds, SampleTag, shortDate, Skeleton, UNKNOWN, useHome } from "./HomeData";

const COULDNT_LOAD = "Couldn't load this just now";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function cashTile(cash: RtDashboard["cash"]): Tile {
  const label = "Cash in bank";
  if (isTileError(cash)) return { label, value: UNKNOWN, sub: COULDNT_LOAD };
  if (!cash) return { label, value: UNKNOWN, sub: "Could not read the bank statements" };
  if (cash.balance_pence === null) return { label, value: UNKNOWN, sub: "Import a statement and match a line", href: "/bank" };
  const reconciled = cash.reconciled_to ? ` · reconciled to ${shortDate(cash.reconciled_to)}` : "";
  return { label, value: pounds(cash.balance_pence), sub: `Balance on ${shortDate(cash.as_of)}${reconciled}` };
}

function owedToYouTile(owed: RtDashboard["owed_to_you"]): Tile {
  const label = "Owed to you";
  if (isTileError(owed)) return { label, value: UNKNOWN, sub: COULDNT_LOAD };
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
  if (isTileError(owed)) return { label, value: UNKNOWN, sub: COULDNT_LOAD };
  if (!owed) return { label, value: UNKNOWN, sub: "Could not read the ledger" };
  const oldest = owed.oldest_days !== null ? `, oldest ${plural(owed.oldest_days, "day")}` : "";
  return { label, value: pounds(owed.total_pence), sub: owed.documents ? `${plural(owed.documents, "unpaid bill")}${oldest}` : "Nothing unpaid" };
}

function vatTile(vat: RtDashboard["vat"], annual: boolean): Tile {
  if (annual) return { label: "VAT estimate", value: UNKNOWN, sub: "Annual returns are not estimated yet" };
  if (isTileError(vat)) return { label: "VAT estimate", value: UNKNOWN, sub: COULDNT_LOAD };
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
  if (isTileError(a)) return { label, value: UNKNOWN, sub: COULDNT_LOAD };
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

const NUMBER_LABELS = ["Cash in bank", "Owed to you", "Owed by you", "VAT estimate"];

function errorTiles(): Tile[] {
  return NUMBER_LABELS.map((label) => ({ label, value: UNKNOWN, sub: "Could not reach your books" }));
}

/** One figure without card chrome (the Today card is the card): label, value, then its link. */
function NumberBlock({ tile }: { tile: Tile }) {
  const valueClass = tile.tone === "amber" ? "text-amber" : "text-ink";
  const subClass = `text-[13px] font-semibold ${tile.tone === "amber" ? "text-amber" : "text-muted"}`;
  return (
    <div role="group" aria-label={tile.label}>
      <p className="min-h-5 text-sm font-semibold text-muted">{tile.label}</p>
      <p className={`mt-1 min-h-8 text-[28px] leading-tight font-extrabold tracking-tight tabular-nums sm:text-3xl ${valueClass}`}>{tile.value}</p>
      {tile.href ? (
        <Link href={tile.href} className={`mt-1 inline-block hover:underline ${subClass}`}>
          {tile.sub}
        </Link>
      ) : (
        <p className={`mt-1 min-h-5 ${subClass}`}>{tile.sub}</p>
      )}
    </div>
  );
}

/**
 * Home › Today: the greeting plus the four key figures from GET /books/dashboard
 * (the Bramblewood sample when signed out). The figures sit in the one `aria-live`
 * region on Home, so screen readers hear them land; the skeleton blocks reserve
 * their heights so nothing below moves.
 */
export function TodayCard() {
  const home = useHome();
  const sample = home.mode === "sample";
  const tiles: Tile[] | null =
    sample ? sampleTiles.slice(0, 4)
    : home.mode === "live" ? liveTiles(home.data, home.annualVat).slice(0, 4)
    : home.mode === "error" ? errorTiles()
    : null;

  return (
    <section aria-label="Today" className="col-span-full rounded-2xl border border-border bg-white p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <Greeting />
        </div>
        <ExplainMore title="Where these figures come from" anchor="books">
          Cash, what you are owed, what you owe and the VAT so far are worked out by code from your books — the sample
          Bramblewood figures when signed out. No model writes these numbers.
        </ExplainMore>
      </div>
      {tiles === null ? (
        <div aria-busy="true" className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {NUMBER_LABELS.map((label) => (
            <div key={label}>
              <p className="text-sm font-semibold text-muted">{label}</p>
              <Skeleton className="mt-2 h-8 w-24" />
              <Skeleton className="mt-2 h-5 w-36 max-w-full" />
            </div>
          ))}
        </div>
      ) : (
        <div aria-live="polite" className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {tiles.map((tile) => <NumberBlock key={tile.label} tile={tile} />)}
        </div>
      )}
      {sample ? (
        <ByWhom className="mt-3" code="Sample figures from the fictional Bramblewood books" ai="no AI involved" />
      ) : (
        <ByWhom className="mt-3" code="Figures by code from your books" ai="no AI involved" />
      )}
      <div className="mt-4">
        <Link
          href="/review"
          className="inline-block whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
        >
          Review your books
        </Link>
        {sample && <SampleTag />}
      </div>
    </section>
  );
}

/**
 * Home › Needs attention: the one count from GET /books/dashboard, with the one
 * place to clear it. Signed out it shows the sample's three proposals.
 */
export function AttentionCard() {
  const home = useHome();
  const sample = home.mode === "sample";
  const tile: Tile | null =
    sample ? sampleTiles[4]
    : home.mode === "live" ? attentionTile(home.data.attention)
    : home.mode === "error" ? { label: "Needs attention", value: UNKNOWN, sub: "Could not reach your books" }
    : null;

  return (
    <section aria-labelledby="attention-heading" className="flex flex-col rounded-2xl border border-border bg-white p-4 sm:p-5">
      <div className="flex items-center gap-2">
        <h2 id="attention-heading" className="text-lg font-extrabold tracking-tight">
          Needs attention{sample && <SampleTag />}
        </h2>
        <ExplainMore title="What this count is" anchor="receipts">
          One number for everything waiting: proposals to approve, readings to look at, unmatched bank lines and
          overdue invoices. Code counts them from your books; you clear them one tap at a time in Review.
        </ExplainMore>
      </div>
      {tile === null ? (
        <div aria-busy="true">
          <Skeleton className="mt-2 h-9 w-16" />
          <Skeleton className="mt-2 h-5 w-40 max-w-full" />
        </div>
      ) : (
        <div role="group" aria-label={tile.label} className="mt-1">
          <p className={`min-h-9 text-3xl font-extrabold tracking-tight tabular-nums ${tile.tone === "warn" ? "text-warn-ink" : "text-ink"}`}>
            {tile.value}
          </p>
          <p className={`mt-1 min-h-5 text-[13px] font-semibold ${tile.tone === "warn" ? "text-warn-ink" : "text-muted"}`}>
            {tile.sub}
          </p>
        </div>
      )}
      <ByWhom
        className="mt-2"
        code={sample ? "Sample count from the fictional Bramblewood books" : "Counted by code from your books"}
        ai={sample ? "sample readings, not AI" : "proposals read by AI"}
      />
      <div className="mt-auto pt-4">
        {tile !== null && tile.href ? (
          <Link
            href={tile.href}
            className="inline-block whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
          >
            {tile.href === "/review" ? `Review ${tile.value} item${tile.value === "1" ? "" : "s"}`
              : tile.href === "/bank" ? "Match bank lines"
              : "Chase overdue invoices"}
          </Link>
        ) : (
          <Link
            href="/review"
            className="inline-block whitespace-nowrap rounded-xl border border-border px-4 py-2 text-sm font-bold text-teal-dark hover:bg-ground"
          >
            Open Review
          </Link>
        )}
      </div>
    </section>
  );
}
