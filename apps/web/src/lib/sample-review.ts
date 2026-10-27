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
  verifierNote: string;
  /** agree = all fields matched; differ = a field disagreed; none = not run or unavailable. */
  verifierTone?: "agree" | "differ" | "none";
  /** Both readings of each field that disagreed, for the user to choose between. */
  verifierDiffs?: { field: string; extractor: string; verifier: string }[];
}

export const proposal: Proposal = {
  id: "screwfix-38-47",
  supplier: "Screwfix",
  total: "£38.47",
  confidence: "Confidence 94%",
  source: "Read by Glimmer 30B on your machine",
  date: "21 Oct 2026",
  vatNumber: "GB 232 5551 12 ✓",
  net: "£32.06",
  vat: "£6.41",
  paidBy: "Card ending 4471",
  lines: [
    {
      account: "Tools & small equipment £32.06",
      amount: "£32.06",
      meaning: "Expense, standard-rated 20%",
    },
    {
      account: "VAT to reclaim £6.41",
      amount: "£6.41",
      meaning: "Goes to Box 4",
    },
    {
      account: "Paid from business card £38.47",
      amount: "£38.47",
      meaning: "Will match a bank line",
    },
  ],
  reviewerNote:
    "Why: 3 lines are drill bits and screws; you approved Screwfix as “Tools & small equipment” on 14 Oct. Totals add up (32.06 + 6.41 = 38.47). — Reviewer, Muse Spark",
  verifierNote:
    "Verifier agrees · all 6 fields match — Muse Spark Open (sample)",
  verifierTone: "agree",
};
