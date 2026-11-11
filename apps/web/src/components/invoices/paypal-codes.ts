import type { RtPaypalSyncItem } from "@/lib/runtime";

/** The cost accounts a PayPal purchase can go to (services/runtime/app/journal.py CATEGORY_ACCOUNTS and Sundry). */
export const COST_ACCOUNTS = [
  "5000 Materials",
  "5100 Tools & small equipment",
  "6200 Advertising",
  "7100 Rent",
  "7200 Utilities",
  "7300 Motor expenses",
  "7400 Travel",
  "7410 Subsistence",
  "7500 Office supplies",
  "7510 Software & subscriptions",
  "7520 Postage",
  "7550 Telephone & internet",
  "7600 Professional fees",
  "7700 Insurance",
  "7900 Bank charges",
  "7999 Sundry expenses",
];
export const VAT_CODES: Record<string, string> = {
  S: "Standard 20%",
  R: "Reduced 5%",
  Z: "Zero rated",
  E: "Exempt",
  N: "No VAT to reclaim",
  O: "Outside the scope of VAT",
};
export const KIND: Record<RtPaypalSyncItem["kind"], string> = {
  invoice: "Invoice payment",
  sale: "Sale",
  expense: "Purchase",
  fee: "PayPal fee",
  withdrawal: "Withdrawal to bank",
  deposit: "Added from bank",
  refund: "Refund or reversal",
  other: "Not posted",
};

/** The VAT codes a PayPal purchase can be approved with (the same list the card editor offers). */
export const PURCHASE_VAT = ["S", "R", "Z", "E", "N"];
