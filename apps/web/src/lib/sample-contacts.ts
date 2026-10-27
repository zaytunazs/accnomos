import type { RtAged, RtContactRow } from "./runtime";

/** Shown when signed out. SAMPLE — FICTIONAL COMPANY. */
const base: Pick<RtContactRow, "aliases" | "edited" | "address" | "default_vat_code" | "created_at" | "updated_at"> = {
  aliases: [],
  edited: [],
  address: null,
  default_vat_code: "S",
  created_at: "2026-10-01T09:00:00Z",
  updated_at: "2026-10-26T09:00:00Z",
};

const totals = {
  documents: 0,
  ytd_sales_net_pence: 0,
  ytd_sales_vat_pence: 0,
  ytd_purchases_net_pence: 0,
  ytd_purchases_vat_pence: 0,
  open_receivable_pence: 0,
  open_payable_pence: 0,
  balance_pence: 0,
  last_activity: null,
};

export const sampleContacts: RtContactRow[] = [
  {
    ...base, id: "5a11c0ffee000001", kind: "customer", name: "Acme Kitchens Ltd", normalised_key: "acme-kitchens",
    vrn: null, email: "accounts@acme-kitchens.example", phone: null, default_category: null, default_vat_code: null, source: "ledger",
    totals: { ...totals, documents: 3, ytd_sales_net_pence: 145000, ytd_sales_vat_pence: 29000, open_receivable_pence: 54000, balance_pence: 54000, last_activity: "2026-09-15" },
  },
  {
    ...base, id: "5a11c0ffee000002", kind: "supplier", name: "Howdens Joinery", normalised_key: "howdens-joinery",
    vrn: "GB123456789", email: null, phone: "0161 496 0000", default_category: "Materials", source: "ledger",
    totals: { ...totals, documents: 2, ytd_purchases_net_pence: 25000, ytd_purchases_vat_pence: 5000, open_payable_pence: 24000, balance_pence: -24000, last_activity: "2026-09-30" },
  },
  {
    ...base, id: "5a11c0ffee000003", kind: "supplier", name: "Screwfix Direct", normalised_key: "screwfix-direct",
    vrn: "GB232456789", email: null, phone: null, default_category: "Tools & small equipment", source: "ledger",
    totals: { ...totals, documents: 4, ytd_purchases_net_pence: 18556, ytd_purchases_vat_pence: 3711, last_activity: "2026-10-21" },
  },
  {
    ...base, id: "5a11c0ffee000004", kind: "customer", name: "Bloggs & Co", normalised_key: "bloggs-and",
    vrn: null, email: null, phone: null, default_category: null, default_vat_code: null, source: "ledger",
    totals: { ...totals, documents: 1, ytd_sales_net_pence: 667, ytd_sales_vat_pence: 133, open_receivable_pence: 800, balance_pence: 800, last_activity: "2026-06-01" },
  },
];

const zero = { "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0 };

export const sampleAged: RtAged = {
  as_of: "2026-10-26",
  debtors: {
    rows: [
      { contact_id: "5a11c0ffee000001", name: "Acme Kitchens Ltd", buckets: { ...zero, "31-60": 54000 }, total_pence: 54000, documents: [] },
      { contact_id: "5a11c0ffee000004", name: "Bloggs & Co", buckets: { ...zero, "90+": 800 }, total_pence: 800, documents: [] },
    ],
    buckets: { ...zero, "31-60": 54000, "90+": 800 },
    total_pence: 54800,
  },
  creditors: {
    rows: [{ contact_id: "5a11c0ffee000002", name: "Howdens Joinery", buckets: { ...zero, "0-30": 24000 }, total_pence: 24000, documents: [] }],
    buckets: { ...zero, "0-30": 24000 },
    total_pence: 24000,
  },
};
