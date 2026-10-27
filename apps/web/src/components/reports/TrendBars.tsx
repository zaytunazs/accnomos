import type { RtTrendMonth } from "@/lib/runtime";

const money = (pence: number) => (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
const whole = (pence: number) => `£${Math.round(pence / 100).toLocaleString("en-GB")}`;

// Teal for sales, amber for purchases, ink for net: separable without colour
// (solid vs dashed vs dotted), with a legend, point titles and the table below.
const SALES = "#0f6e63";
const PURCHASES = "#b45309";
const NET = "#1b1f24";
const GRID = "#e3e1d8";
const MUTED = "#4b5159";

const W = 720;
const H = 260;
const PAD = { top: 12, right: 12, bottom: 30, left: 56 };

/** Round a step up to 1, 2 or 5 × a power of ten (pence). */
function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1)));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? 10 * p;
}

function points(months: RtTrendMonth[], pick: (m: RtTrendMonth) => number, x: (i: number) => number, y: (p: number) => number): string {
  return months.map((m, i) => `${x(i).toFixed(1)},${y(pick(m)).toFixed(1)}`).join(" ");
}

/**
 * Twelve months of sales, purchases (cost of sales + overheads) and net as
 * three lines. Inline SVG, no library; one y-axis in pounds. The figures are
 * also in the table under it.
 */
export default function TrendBars({ months }: { months: RtTrendMonth[] }) {
  const values = months.flatMap((m) => [m.sales_pence, m.purchases_pence, m.net_pence]);
  const step = niceStep(Math.max(...values.map(Math.abs), 100) / 4);
  const top = Math.ceil(Math.max(...values, 0) / step) * step || step;
  const bottom = Math.floor(Math.min(...values, 0) / step) * step;
  const plotH = H - PAD.top - PAD.bottom;
  const plotW = W - PAD.left - PAD.right;
  const y = (p: number) => PAD.top + ((top - p) / (top - bottom)) * plotH;
  const x = (i: number) => PAD.left + (months.length === 1 ? plotW / 2 : (i / (months.length - 1)) * plotW);
  const ticks: number[] = [];
  for (let v = bottom; v <= top; v += step) ticks.push(v);
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
                {m.label.replace(/ (\d{4})$/, "").slice(0, 3)}
                {m.month.endsWith("-01") || i === 0 ? ` ’${m.month.slice(2, 4)}` : ""}
              </text>
            )}
          </g>
        ))}
      </svg>
    </figure>
  );
}
