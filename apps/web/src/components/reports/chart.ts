/**
 * Shared pieces for the inline SVG charts (no chart library): the brand's series colours, the pounds formats and the
 * y-axis maths. Used by the Reports trend (TrendBars), Home's monthly chart and the cash forecast line.
 */

// Teal for sales, amber for purchases, ink for net. Each series also differs by shape (solid, dashed, dotted, bars
// against a line), and every chart has a legend, point titles and the same figures as a table.
export const SALES = "#0f6e63";
export const PURCHASES = "#b45309";
export const NET = "#1b1f24";
export const GRID = "#e3e1d8";
export const MUTED = "#4b5159";

export type Pad = { top: number; right: number; bottom: number; left: number };

/** "£1,240" from pence, for titles and labels. */
export const money = (pence: number) =>
  (pence / 100).toLocaleString("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });

/** "£1,240" for an axis tick (whole pounds, no currency rounding quirks). */
export const whole = (pence: number) => `${pence < 0 ? "-" : ""}£${Math.round(Math.abs(pence) / 100).toLocaleString("en-GB")}`;

/** Round a step up to 1, 2 or 5 × a power of ten (pence). */
export function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1)));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? 10 * p;
}

/**
 * A y-axis that always includes zero, with about `lines` gridlines at round amounts.
 * `y(p)` maps pence to the SVG y between `pad.top` and `height - pad.bottom`.
 */
export function yAxis(values: number[], height: number, pad: Pad, lines = 4) {
  const step = niceStep(Math.max(...values.map(Math.abs), 100) / lines);
  const top = Math.ceil(Math.max(...values, 0) / step) * step || step;
  const bottom = Math.floor(Math.min(...values, 0) / step) * step;
  const plotH = height - pad.top - pad.bottom;
  const y = (p: number) => pad.top + ((top - p) / (top - bottom)) * plotH;
  const ticks: number[] = [];
  for (let v = bottom; v <= top; v += step) ticks.push(v);
  return { y, ticks, top, bottom };
}

/** "Oct" for a "2026-10" month, with "’26" added on January and on the first month shown. */
export function monthTick(month: string, label: string, first: boolean): string {
  const short = label.replace(/ (\d{4})$/, "").slice(0, 3);
  return month.endsWith("-01") || first ? `${short} ’${month.slice(2, 4)}` : short;
}
