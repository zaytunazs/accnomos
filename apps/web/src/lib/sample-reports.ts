import type { RtProfitAndLoss, RtTrend, RtTrendMonth, RtVatSummary } from "./runtime";
import { sampleAged } from "./sample-contacts";

/**
 * Shown on /reports when signed out. SAMPLE — FICTIONAL COMPANY. Pence, as the runtime sends them.
 * Jul–Sep 2026 agrees with the sample VAT return (box 6 £31,900) and with the trend's Jul, Aug and Sep.
 */
export const samplePl: RtProfitAndLoss = {
  start: "2026-07-01",
  end: "2026-09-30",
  label: "Jul–Sep 2026",
  basis:
    "As approved: each entry counts on its own date (invoices when raised, receipts when bought); an undo counts on the date it was made. Not a cash-basis view.",
  sales: { rows: [{ account: "4000 Sales", amount_pence: 3_190_000 }], total_pence: 3_190_000 },
  cost_of_sales: {
    rows: [
      { account: "5000 Materials", amount_pence: 1_412_000 },
      { account: "5100 Tools & small equipment", amount_pence: 186_000 },
    ],
    total_pence: 1_598_000,
  },
  gross_profit_pence: 1_592_000,
  overheads: {
    rows: [
      { account: "6200 Advertising", amount_pence: 24_000 },
      { account: "7000 Gross wages", amount_pence: 540_000 },
      { account: "7010 Employer's NI", amount_pence: 41_500 },
      { account: "7300 Motor expenses", amount_pence: 96_000 },
      { account: "7310 Motor — mileage allowance", amount_pence: 31_500 },
      { account: "7500 Office supplies", amount_pence: 12_400 },
      { account: "7510 Software & subscriptions", amount_pence: 18_000 },
      { account: "7550 Telephone & internet", amount_pence: 13_500 },
      { account: "7700 Insurance", amount_pence: 42_000 },
      { account: "7900 Bank charges", amount_pence: 2_600 },
    ],
    total_pence: 821_500,
  },
  net_profit_pence: 770_500,
  entries: 55,
  sample: true,
};

const MONTHS: [string, number, number][] = [
  ["2025-11", 720_000, 610_000],
  ["2025-12", 540_000, 580_000],
  ["2026-01", 610_000, 520_000],
  ["2026-02", 690_000, 560_000],
  ["2026-03", 880_000, 640_000],
  ["2026-04", 820_000, 700_000],
  ["2026-05", 940_000, 720_000],
  ["2026-06", 1_010_000, 760_000],
  ["2026-07", 1_050_000, 790_000],
  ["2026-08", 980_000, 760_500],
  ["2026-09", 1_160_000, 869_000],
  ["2026-10", 640_000, 455_000],
];

function month([m, sales, purchases]: [string, number, number]): RtTrendMonth {
  const [y, mm] = m.split("-").map(Number);
  const end = new Date(Date.UTC(y, mm, 0)).getUTCDate();
  const label = new Date(Date.UTC(y, mm - 1, 1)).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  return { month: m, label, start: `${m}-01`, end: `${m}-${end}`, sales_pence: sales, purchases_pence: purchases, net_pence: sales - purchases };
}

export const sampleTrend: RtTrend = { months: MONTHS.map(month), sample: true };

export const sampleVat: RtVatSummary = {
  periods: [
    { period: "2026-Q1", start: "2026-01-01", end: "2026-03-31", label: "Jan–Mar 2026", vat_on_sales_pence: 436_000, vat_reclaimed_pence: 322_000, net_vat_pence: 114_000, sales_ex_vat_pounds: 21_800, purchases_ex_vat_pounds: 16_100, entries: 48, warnings: [] },
    { period: "2026-Q2", start: "2026-04-01", end: "2026-06-30", label: "Apr–Jun 2026", vat_on_sales_pence: 554_000, vat_reclaimed_pence: 359_000, net_vat_pence: 195_000, sales_ex_vat_pounds: 27_700, purchases_ex_vat_pounds: 17_950, entries: 51, warnings: [] },
    { period: "2026-Q3", start: "2026-07-01", end: "2026-09-30", label: "Jul–Sep 2026", vat_on_sales_pence: 638_000, vat_reclaimed_pence: 424_000, net_vat_pence: 214_000, sales_ex_vat_pounds: 31_900, purchases_ex_vat_pounds: 22_850, entries: 55, warnings: [] },
    { period: "2026-Q4", start: "2026-10-01", end: "2026-12-31", label: "Oct–Dec 2026", vat_on_sales_pence: 128_000, vat_reclaimed_pence: 91_000, net_vat_pence: 37_000, sales_ex_vat_pounds: 6_400, purchases_ex_vat_pounds: 4_550, entries: 12, warnings: [] },
  ],
  total_net_vat_pence: 560_000,
  sample: true,
};

export { sampleAged };
