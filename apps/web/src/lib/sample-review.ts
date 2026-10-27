import type { RtCheck, RtProposal, RtRule } from "./runtime";

export interface ProposalLine {
  account: string;
  amount: string;
  meaning: string;
}

export interface Proposal {
  id: string;
  supplier: string;
  total: string;
  confidence: string;
  source: string;
  date: string;
  vatNumber: string;
  net: string;
  vat: string;
  paidBy: string;
  lines: ProposalLine[];
  reviewerNote: string;
  /** One plain-English line per failed or warning check (never the check's code). */
  failedChecks?: { text: string; warn: boolean }[];
  verifierNote: string;
  /** agree = all fields matched; differ = a field disagreed; none = not run or unavailable. */
  verifierTone?: "agree" | "differ" | "none";
  /** Both readings of each field that disagreed, for the user to choose between. */
  verifierDiffs?: { field: string; extractor: string; verifier: string }[];
}

/*
 * Signed out: SAMPLE — FICTIONAL COMPANY (Bramblewood Joinery Ltd). Real proposal shapes, so the sample page
 * runs the same card, keyboard, edit, rule and undo code as the live one; decisions stay in this browser tab.
 */

const passed = (...extra: RtCheck[]): RtCheck[] => [
  { code: "ARITH_TOTALS", ok: true, severity: "fail", message: "Totals add up" },
  { code: "VAT_MATH", ok: true, severity: "fail", message: "VAT is 20% of net" },
  { code: "VAT_RATE_VALID", ok: true, severity: "fail", message: "VAT rates are 0/5/20%" },
  { code: "VAT_NUMBER_FORMAT", ok: true, severity: "fail", message: "VAT number looks valid" },
  { code: "CURRENCY", ok: true, severity: "fail", message: "In pounds sterling" },
  { code: "DATE_VALID", ok: true, severity: "fail", message: "Date is valid" },
  { code: "CONFIDENCE", ok: true, severity: "fail", message: "Reading is confident" },
  ...extra,
];

const agree = (fields: Record<string, string | number | null>) => ({
  agree_all: true,
  model: "baseten:muse-spark-open",
  fields: Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, { extractor: v, verifier: v, agree: true }])),
});

function purchase(
  id: string,
  supplier: string,
  vrn: string | null,
  date: string,
  netP: number,
  vatP: number,
  category: string,
  account: string,
  over: Partial<RtProposal> = {},
): RtProposal {
  const gross = netP + vatP;
  return {
    id,
    doc_sha256: `sample-${id}`,
    extracted: {
      doc_type: "receipt", supplier_name: supplier, supplier_vat_number: vrn, customer_name: null, invoice_number: null,
      date, currency: "GBP",
      lines: [{ description: category, qty: 1, unit_price: netP / 100, net: netP / 100, vat_rate: 20, vat: vatP / 100 }],
      net_total: netP / 100, vat_total: vatP / 100, gross_total: gross / 100,
      payment_method: "card", card_last4: "4471", category_guess: category, confidence: 0.94,
    },
    checks: passed({ code: "VERIFIER_AGREES", ok: true, severity: "fail", message: "Verifier agrees · all 6 fields match" }),
    status: "proposed",
    reasons: [],
    suggested_filename: `${date} ${supplier} £${(gross / 100).toFixed(2)}.jpg`,
    journal_draft: [
      { account, debit_pence: netP, credit_pence: 0, vat_code: "S" },
      { account: "2200 VAT control", debit_pence: vatP, credit_pence: 0, vat_code: "S" },
      { account: "1200 Bank", debit_pence: 0, credit_pence: gross, vat_code: null },
    ],
    model: "local:glimmer-30b",
    elapsed_s: 6.2,
    crop: { method: "none", box: null, note: "" },
    verification: agree({
      supplier_name: supplier, supplier_vat_number: vrn, date, net_total: netP / 100, vat_total: vatP / 100, gross_total: gross / 100,
    }),
    autopilot: { auto_approve: false, reasons: ["Autopilot is switched off"], supplier_key: null },
    ...over,
  };
}

export const SAMPLE_IMAGE = "/sample-receipt.png"; // public/: Novex on a table, so the crop has something to cut away

export function sampleProposals(): RtProposal[] {
  const novex = purchase("sample-novex", "Novex Office Supplies Ltd", "GB882431902", "2026-11-02", 4325, 865, "Office supplies", "7500 Office supplies", {
    model: "meta:muse-spark",
    crop: { method: "code", box: [104, 20, 646, 618], note: "Cropped by code" },
    status: "needs_a_look",
    reasons: ["VERIFIER_AGREES: Second reading differs: Date 2026-11-02 vs 2026-10-02"],
  });
  novex.extracted.lines = [
    { description: "A4 Paper Ream (80gsm)", qty: 2, unit_price: 12.5, net: 25, vat_rate: 20, vat: 5 },
    { description: "Gel Pens Black (10pk)", qty: 1, unit_price: 18.25, net: 18.25, vat_rate: 20, vat: 3.65 },
  ];
  novex.extracted.card_last4 = "4821";
  novex.checks = passed({ code: "VERIFIER_AGREES", ok: false, severity: "fail", message: "Second reading differs: Date 2026-11-02 vs 2026-10-02" });
  novex.verification!.agree_all = false;
  novex.verification!.model = "meta:muse-spark";
  novex.verification!.fields.date = { extractor: "2026-11-02", verifier: "2026-10-02", agree: false };

  const travis = purchase("sample-travis", "Travis Perkins", "GB408556737", "2026-10-21", 17700, 3540, "Materials", "5000 Materials", {
    status: "needs_a_look",
    reasons: ["DUPLICATE: Looks like a duplicate of a receipt you approved on 14 Oct (same supplier, same total, invoice TP-88213)"],
    verification: null,
  });
  travis.checks = passed({
    code: "DUPLICATE", ok: false, severity: "fail",
    message: "Looks like a duplicate of a receipt you approved on 14 Oct (same supplier, same total, invoice TP-88213)",
  });

  return [
    purchase("sample-screwfix-1", "Screwfix", "GB232555112", "2026-10-21", 3206, 641, "Tools & small equipment", "5100 Tools & small equipment"),
    purchase("sample-screwfix-2", "Screwfix", "GB232555112", "2026-10-24", 1800, 360, "Tools & small equipment", "5100 Tools & small equipment"),
    novex,
    travis,
  ];
}

/** The rule "Always do this for Screwfix" saved on an earlier approval. */
export const sampleRules: RtRule[] = [
  {
    supplier_key: "screwfix", supplier_name: "Screwfix", category: "Tools & small equipment",
    account: "5100 Tools & small equipment", vat_code: "S", side: "purchase", typical_gross_pence: 3847,
    vrn: "GB232555112", created_at: "2026-10-14T09:12:00Z", created_from_proposal_id: "sample-screwfix-0", hits: 3,
  },
];
