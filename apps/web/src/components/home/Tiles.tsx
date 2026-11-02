"use client";

import Link from "next/link";
import ByWhom from "@/components/ByWhom";
import ExplainMore from "@/components/ExplainMore";
import { isTileError, tileData, type RtDashboard, type RtHome } from "@/lib/runtime";
import { sampleAttention, tiles as sampleTiles, type Tile } from "@/lib/sample-home";
import Greeting from "./Greeting";
import { pounds, SampleTag, shortDate, Skeleton, UNKNOWN, useHome, useVatApplies } from "./HomeData";
import { daysWord } from "./OverviewCards";
import { useOverview } from "./Overview";

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

/** The key figures; VAT only when the profile has it (personal books and non-VAT businesses have no VAT tile). */
function liveTiles(d: RtDashboard, annualVat: boolean, vat: boolean): Tile[] {
  return [cashTile(d.cash), owedToYouTile(d.owed_to_you), owedByYouTile(d.owed_by_you),
    ...(vat ? [vatTile(d.vat, annualVat)] : [])];
}

const NUMBER_LABELS = ["Cash in bank", "Owed to you", "Owed by you", "VAT estimate"];
const numberLabels = (vat: boolean) => (vat ? NUMBER_LABELS : NUMBER_LABELS.filter((l) => l !== "VAT estimate"));

function errorTiles(vat: boolean): Tile[] {
  return numberLabels(vat).map((label) => ({ label, value: UNKNOWN, sub: "Could not reach your books" }));
}

/** One figure without card chrome (the Today card is the card): label, value, then its link. */
function NumberBlock({ tile }: { tile: Tile }) {
  const valueClass = tile.tone === "amber" ? "text-amber" : "text-ink";
  const subClass = `text-[13px] font-semibold ${tile.tone === "amber" ? "text-amber" : "text-muted"}`;
  return (
    <div role="group" aria-label={tile.label}>
      <p className="min-h-5 text-sm font-semibold text-muted">{tile.label}</p>
      <p className={`mt-1 min-h-8 text-[28px] leading-tight font-bold tracking-tight tabular-nums sm:text-3xl ${valueClass}`}>{tile.value}</p>
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
  const vat = useVatApplies();
  const sample = home.mode === "sample";
  const tiles: Tile[] | null =
    sample ? sampleTiles.slice(0, 4)
    : home.mode === "live" ? liveTiles(home.data, home.annualVat, vat)
    : home.mode === "error" ? errorTiles(vat)
    : null;

  return (
    <section aria-label="Today" className="col-span-full rounded-2xl border border-border bg-white p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <Greeting />
        </div>
        <ExplainMore title="Where these figures come from" anchor="books">
          Cash, what you are owed, what you owe{vat ? " and the VAT so far" : ""} are worked out by code from your books — the sample
          Bramblewood figures when signed out. No model writes these numbers.
        </ExplainMore>
      </div>
      {tiles === null ? (
        <div aria-busy="true" className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {numberLabels(vat).map((label) => (
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

type Attention = Extract<NonNullable<RtDashboard["attention"]>, { proposed: number }>;

export interface AttentionTile {
  key: string;
  label: string;
  /** The big figure, or a short phrase ("Up to date"). */
  value: string;
  /** Beside a number: "days", "days late". */
  unit?: string;
  text: string;
  href: string;
  /** Something waits (warm tone and an alert icon) or nothing does (a tick). */
  waiting: boolean;
}

/** Items to review, overdue invoices and bank lines to reconcile, from the dashboard's `attention` counts. */
function attentionTiles(a: Attention): AttentionTile[] {
  const review = a.proposed + a.needs_a_look;
  const tiles: AttentionTile[] = [
    {
      key: "review",
      label: "Items to review",
      value: String(review),
      text: review
        ? [a.proposed && `${a.proposed} to approve`, a.needs_a_look && `${a.needs_a_look} to look at`].filter(Boolean).join(" · ")
        : "Nothing to review",
      href: "/review",
      waiting: review > 0,
    },
  ];
  // Missing information (readings that need a look) is already inside the first tile: it is not counted twice here.
  if (a.overdue_invoices !== null)
    tiles.push({
      key: "overdue",
      label: "Overdue invoices",
      value: String(a.overdue_invoices),
      text: a.overdue_invoices ? `${plural(a.overdue_invoices, "invoice")} to chase` : "None overdue",
      href: "/invoices",
      waiting: a.overdue_invoices > 0,
    });
  tiles.push({
    key: "bank",
    label: "Bank lines to reconcile",
    value: String(a.unmatched_bank_lines),
    text: a.unmatched_bank_lines ? `${plural(a.unmatched_bank_lines, "line")} to match` : "All matched",
    href: "/bank/reconcile",
    waiting: a.unmatched_bank_lines > 0,
  });
  return tiles;
}

/** The nearest dated obligation (VAT, MTD Income Tax, payroll, CIS) from GET /books/home, or "Up to date" when none is within 14 days. */
function deadlineTile(deadlines: RtHome["deadlines"]): AttentionTile {
  const next = [...deadlines].sort((x, y) => x.days_left - y.days_left)[0];
  if (!next || next.days_left > 14)
    return { key: "deadline", label: "On track", value: "Up to date", text: "Nothing due in the next 14 days", href: next?.href ?? "/vat", waiting: false };
  return {
    key: "deadline",
    label: "Next deadline",
    value: String(Math.abs(next.days_left)),
    unit: `${Math.abs(next.days_left) === 1 ? "day" : "days"}${next.days_left < 0 ? " late" : next.days_left === 0 ? "" : " left"}`,
    text: `${next.title}, ${shortDate(next.due)} (${daysWord(next.days_left)})`,
    href: next.href,
    waiting: true,
  };
}

function TileIcon({ waiting }: { waiting: boolean }) {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      {waiting ? (
        <>
          <circle cx="10" cy="10" r="7.5" />
          <path d="M10 6v4.5M10 13.6v.1" />
        </>
      ) : (
        <>
          <circle cx="10" cy="10" r="7.5" />
          <path d="m6.8 10.2 2.2 2.2 4.2-4.6" />
        </>
      )}
    </svg>
  );
}

export function AttentionLink({ tile }: { tile: AttentionTile }) {
  // A white card whatever the state (the brief: no row of coloured cards); the state is the tinted icon square and the
  // words, so colour never carries it alone.
  return (
    <li className="flex">
      <Link
        href={tile.href}
        data-waiting={tile.waiting ? "" : undefined}
        className="flex w-full min-w-0 flex-col rounded-2xl border border-border bg-white p-3 text-ink hover:border-teal/40 hover:bg-ground sm:p-4"
      >
        <span className="flex items-center gap-2.5 text-[13px] font-semibold text-muted">
          <span
            aria-hidden="true"
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
              tile.waiting ? "bg-warn-bg text-warn-ink" : "bg-teal-tint text-teal-dark"
            }`}
          >
            <TileIcon waiting={tile.waiting} />
          </span>
          <span className="min-w-0 text-ink">{tile.label}</span>
        </span>
        <span className={`mt-2 font-bold leading-tight tracking-tight tabular-nums ${tile.value.length > 3 ? "text-xl sm:text-2xl" : "text-[28px]"}`}>
          {tile.value}
          {tile.unit && <span className="ml-1 text-sm font-semibold">{tile.unit}</span>}
        </span>
        <span className={`mt-1 text-[13px] leading-snug ${tile.waiting ? "font-semibold text-warn-ink" : "text-muted"}`}>{tile.text}</span>
      </Link>
    </li>
  );
}

/**
 * Home › what needs attention, under the summary: up to four small tiles (items to review, overdue invoices, bank
 * lines to reconcile, the next deadline), each a link to the place that clears it. Counts come from the one GET
 * /books/dashboard `attention` block and the deadlines from GET /books/home that Home already loads (the Bramblewood
 * sample when signed out). Status is the icon and the words, never colour alone. A count that is not available drops
 * its tile rather than showing a made-up number.
 */
export function AttentionTiles() {
  const home = useHome();
  const overview = useOverview();
  const sample = home.mode === "sample";
  const attention = sample ? sampleAttention : home.mode === "live" ? tileData(home.data.attention) : null;
  const loading = home.mode === "checking" || home.mode === "loading";
  if (home.mode === "error") return null;

  let tiles: AttentionTile[] | null = null;
  if (attention) {
    tiles = attentionTiles(attention);
    if (overview.mode === "live" || overview.mode === "sample") tiles.push(deadlineTile(overview.data.deadlines));
  }
  if (!loading && !tiles) return null;

  return (
    <section aria-label="What needs attention" aria-busy={loading}>
      {tiles ? (
        <ul className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
          {tiles.map((t) => <AttentionLink key={t.key} tile={t} />)}
        </ul>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="min-h-[6.5rem] rounded-2xl border border-border bg-white p-3 sm:p-4">
              <Skeleton className="h-4 w-24 max-w-full" />
              <Skeleton className="mt-3 h-8 w-12" />
            </div>
          ))}
        </div>
      )}
      {sample && <p className="mt-1.5 text-xs font-semibold text-muted">Sample counts from the fictional Bramblewood books</p>}
    </section>
  );
}
