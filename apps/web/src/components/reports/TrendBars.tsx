import type { RtTrendMonth } from "@/lib/runtime";
import { money, monthTick, MUTED, GRID, NET, PURCHASES, SALES, whole, yAxis } from "./chart";

const W = 720;
const H = 260;
const PAD = { top: 12, right: 12, bottom: 30, left: 56 };

function points(months: RtTrendMonth[], pick: (m: RtTrendMonth) => number, x: (i: number) => number, y: (p: number) => number): string {
  return months.map((m, i) => `${x(i).toFixed(1)},${y(pick(m)).toFixed(1)}`).join(" ");
}

/**
 * Twelve months of sales, purchases (cost of sales + overheads) and net as
 * three lines. Inline SVG, no library; one y-axis in pounds. The figures are
 * also in the table under it.
 */
export default function TrendBars({ months }: { months: RtTrendMonth[] }) {
  const { y, ticks } = yAxis(months.flatMap((m) => [m.sales_pence, m.purchases_pence, m.net_pence]), H, PAD);
  const plotW = W - PAD.left - PAD.right;
  const x = (i: number) => PAD.left + (months.length === 1 ? plotW / 2 : (i / (months.length - 1)) * plotW);
  const first = months[0];
  const last = months.at(-1);
  const up = (last?.net_pence ?? 0) >= (first?.net_pence ?? 0);

  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] font-semibold text-muted">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-0.5 w-4" style={{ background: SALES }} /> Sales
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-0.5 w-4" style={{ background: PURCHASES }} /> Purchases (cost of sales + overheads)
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-0.5 w-4" style={{ background: NET }} /> Net
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Sales, purchases and net per month, ${first?.label ?? ""} to ${last?.label ?? ""}. Net ${up ? "rose" : "fell"} from ${money(first?.net_pence ?? 0)} to ${money(last?.net_pence ?? 0)}. The figures are in the table below.`}
        className="h-auto w-full"
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke={v === 0 ? MUTED : GRID} strokeWidth={1} />
            <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill={MUTED}>
              {whole(v)}
            </text>
          </g>
        ))}
        <polyline points={points(months, (m) => m.purchases_pence, x, y)} fill="none" stroke={PURCHASES} strokeWidth={2} strokeDasharray="6 3" strokeLinejoin="round" />
        <polyline points={points(months, (m) => m.sales_pence, x, y)} fill="none" stroke={SALES} strokeWidth={2.5} strokeLinejoin="round" />
        <polyline points={points(months, (m) => m.net_pence, x, y)} fill="none" stroke={NET} strokeWidth={2} strokeDasharray="2 3" strokeLinecap="round" />
        {months.map((m, i) => (
          <g key={m.month}>
            <circle cx={x(i)} cy={y(m.sales_pence)} r={3.5} fill={SALES}>
              <title>{`${m.label}: sales ${money(m.sales_pence)}`}</title>
            </circle>
            <circle cx={x(i)} cy={y(m.purchases_pence)} r={3.5} fill="#fff" stroke={PURCHASES} strokeWidth={2}>
              <title>{`${m.label}: purchases ${money(m.purchases_pence)}`}</title>
            </circle>
            <circle cx={x(i)} cy={y(m.net_pence)} r={3} fill={NET}>
              <title>{`${m.label}: net ${money(m.net_pence)}`}</title>
            </circle>
            {(i % 2 === 0 || i === months.length - 1) && (
              <text x={x(i)} y={H - PAD.bottom + 15} textAnchor="middle" fontSize={11} fill={MUTED}>
                {monthTick(m.month, m.label, i === 0)}
              </text>
            )}
          </g>
        ))}
      </svg>
    </figure>
  );
}
