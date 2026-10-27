export interface VatBox {
  box: number;
  what: string;
  amount: string;
  entries: number | null;
  shaded?: boolean;
  highlight?: boolean;
  warning?: string;
  large?: boolean;
}

export interface VatSampleRow {
  date: string;
  supplier: string;
  vat: string;
}

export const vatBoxes: VatBox[] = [
  { box: 1, what: "VAT due on sales", amount: "£6,380.00", entries: 14 },
  {
    box: 2,
    what: "VAT due on acquisitions from NI/EU",
    amount: "£0.00",
    entries: null,
  },
  {
    box: 3,
    what: "Total VAT due (1 + 2, by code)",
    amount: "£6,380.00",
    entries: null,
    shaded: true,
  },
  {
    box: 4,
    what: "VAT reclaimed on purchases",
    amount: "£4,240.00",
    entries: 41,
    highlight: true,
    warning: "· 1 warning",
  },
  {
    box: 5,
    what: "Net VAT to pay HMRC (3 − 4)",
    amount: "£2,140.00",
    entries: null,
    shaded: true,
    large: true,
  },
  { box: 6, what: "Total sales excluding VAT", amount: "£31,900", entries: 14 },
  {
    box: 7,
    what: "Total purchases excluding VAT",
    amount: "£22,850",
    entries: 41,
  },
  { box: 8, what: "Supplies of goods to NI/EU", amount: "£0", entries: null },
  {
    box: 9,
    what: "Acquisitions of goods from NI/EU",
    amount: "£0",
    entries: null,
  },
];

export const box4SampleRows: VatSampleRow[] = [
  { date: "21 Oct", supplier: "Screwfix", vat: "£6.41" },
  { date: "18 Oct", supplier: "Howdens Joinery", vat: "£412.00" },
  { date: "14 Oct", supplier: "Travis Perkins", vat: "£35.40" },
];

export const vatMeta = {
  period: "Period 1 Jul – 30 Sep 2026 · key 26A3 · due 7 Nov",
  title: "VAT return · Q3 2026",
  status: "HMRC connected (sandbox) · obligation open",
  box4Entries: 41,
  totalEntries: 55,
};
