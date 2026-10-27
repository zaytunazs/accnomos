import type { RtAskAnswer } from "./runtime";

/** Signed-out demo thread (Bramblewood Joinery, fictional). Same story as the mobile Ask screen and sample-vat. */
export const sampleQuestion = "Why is my VAT higher than last quarter?";

export const sampleAnswer: RtAskAnswer = {
  answer_md: [
    "Your Q3 bill is **£2,140.00**, up £620.00 on Q2. Two reasons:",
    "",
    "1. Sales were £6,400.00 higher — the Hartley kitchen job (INV-0039, INV-0041).",
    "2. You reclaimed less: the Howdens invoice (£412.00 VAT) is still waiting for a VAT number, so it's not in Box 4 yet.",
    "",
    "If Howdens sends the VAT invoice before 7 Nov, your bill drops to £1,728.00.",
  ].join("\n"),
  key_numbers: [
    { label: "Net VAT (Box 5), Q3", value: "£2,140.00", source: "05 VAT returns/2026-Q3/return.json" },
    { label: "Net VAT (Box 5), Q2", value: "£1,520.00", source: "05 VAT returns/2026-Q2/return.json" },
    { label: "Howdens VAT waiting", value: "£412.00", source: "04 Needs a look/2026-09-18 Howdens £2,472.00.pdf" },
  ],
  citations: ["05 VAT returns/2026-Q3/return.json", "_System/Ledger/events/2026-09/", "Books.xlsx"],
  suggested_actions: [
    { label: "Chase Howdens for the VAT invoice", kind: "chase_supplier", arg: "Howdens" },
    { label: "Show Box 4 entries", kind: "open_vat", arg: null },
  ],
  confidence: "high",
  model: "Muse Spark",
  period: { start: "2026-07-01", end: "2026-09-30" },
  fallback_reason: null,
};
