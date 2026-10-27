import type { RtTrendMonth } from "@/lib/runtime";

const money = (pence: number) => (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
const whole = (pence: number) => `£${Math.round(pence / 100).toLocaleString("en-GB")}`;

// Brand teal and amber: CVD-separable (ΔE 9.8 protan) but teal sits under the chroma floor, so identity is never
// colour alone — a legend, net as an ink tick, a hover title per month and the table below.
const SALES = "#0f6e63";
const PURCHASES = "#b45309";
const INK = "#1b1f24";
const GRID = "#e3e1d8";
const MUTED = "#4b5159";

const W = 720;
const H = 240;
const PAD = { top: 12, right: 8, bottom: 28, left: 56 };
const BAR = 16;
const GAP = 2; // surface gap between a month's two bars

/** A bar with 4px rounded ends away from the baseline (upwards for positive values). */
function bar(x: number, y0: number, y1: number, w: number): string {
  const top = Math.min(y0, y1);
  const h = Math.abs(y1 - y0);
  if (h < 0.5) return "";
  const r = Math.min(4, h, w / 2);
  return `M${x},${top + h} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${top + h} Z`;
}

/** Round a step up to 1, 2 or 5 × a power of ten (pence). */
function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1)));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? 10 * p;
}

/**
 * Twelve months of sales and purchases (cost of sales + overheads) as paired bars, with each month's net as an ink
 * tick. Inline SVG, no library; one y-axis in pounds. The figures are also in the table under it.
 */
export default function TrendBars({ months }: { months: RtTrendMonth[] }) {
  const values = months.flatMap((m) => [m.sales_pence, m.purchases_pence, m.net_pence]);
  const step = niceStep(Math.max(...values.map(Math.abs), 100) / 4);
  const top = Math.ceil(Math.max(...values, 0) / step) * step || step;
  const bottom = Math.floor(Math.min(...values, 0) / step) * step;
  const plotH = H - PAD.top - PAD.bottom;
  const y = (p: number) => PAD.top + ((top - p) / (top - bottom)) * plotH;
  const slot = (W - PAD.left - PAD.right) / Math.max(months.length, 1);
  const ticks: number[] = [];
  for (let v = bottom; v <= top; v += step) ticks.push(v);

  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] font-semibold text-muted">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: SALES }} /> Sales
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-3 w-3 rounded-sm" style={{ background: PURCHASES }} /> Purchases (cost of sales + overheads)
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-0.5 w-4" style={{ background: INK }} /> Net
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Sales, purchases and net per month, ${months[0]?.label ?? ""} to ${months.at(-1)?.label ?? ""}. The figures are in the table below.`}
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
        {months.map((m, i) => {
          const cx = PAD.left + slot * i + slot / 2;
          const x0 = cx - BAR - GAP / 2;
          const year = i === 0 || m.month.endsWith("-01");
          return (
            <g key={m.month}>
              <path d={bar(x0, y(0), y(m.sales_pence), BAR)} fill={SALES} />
              <path d={bar(cx + GAP / 2, y(0), y(m.purchases_pence), BAR)} fill={PURCHASES} />
              <line x1={x0 - 3} x2={cx + GAP / 2 + BAR + 3} y1={y(m.net_pence)} y2={y(m.net_pence)} stroke={INK} strokeWidth={2} />
              <text x={cx} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={11} fill={MUTED}>
                {m.label.slice(0, 3)}
              </text>
              {year && (
                <text x={cx} y={H - PAD.bottom + 26} textAnchor="middle" fontSize={10} fill={MUTED}>
                  {m.month.slice(0, 4)}
                </text>
              )}
              {/* Hover target: the whole month, bigger than its bars. */}
              <rect x={cx - slot / 2} y={PAD.top} width={slot} height={plotH} fill="transparent">
                <title>{`${m.label}: sales ${money(m.sales_pence)}, purchases ${money(m.purchases_pence)}, net ${money(m.net_pence)}`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
