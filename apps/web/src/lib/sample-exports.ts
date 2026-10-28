/**
 * Signed out, the Reports & exports page shows what it offers with fictional figures. The list is a short,
 * hand-picked part of the runtime's catalogue (services/runtime/app/exports/); signed in, the page lists the
 * runtime's own. Pence throughout, like the runtime.
 */
import type { RtExportCatalogue, RtExportPreview } from "./runtime";

const r = (id: string, group: string, title: string, description: string, formats = ["csv", "xlsx", "pdf"], packageId: string | null = null) => ({
  id,
  group,
  title,
  description,
  formats,
  params: ["period"],
  modes: [],
  package: packageId,
});

export const sampleCatalogue: RtExportCatalogue = {
  groups: [
    { id: "financial", title: "Financial statements" },
    { id: "payables", title: "Payables and receivables" },
    { id: "reconciliations", title: "Reconciliations" },
    { id: "taxes", title: "Taxes and balances" },
    { id: "transactions", title: "Transactions" },
    { id: "pack", title: "For your accountant" },
    { id: "export", title: "Export to another package" },
  ],
  reports: [
    r("balance-sheet", "financial", "Balance sheet", "Assets, liabilities, capital and reserves at the period end."),
    r("profit-and-loss", "financial", "Profit and loss", "With the previous period and the same period last year."),
    r("cash-flow", "financial", "Statement of cash flows (direct method)", "Cash from operating, investing and financing activities."),
    r("aged-receivables-summary", "payables", "Aged receivables summary", "What each customer owes, by age band."),
    r("aged-payables-summary", "payables", "Aged payables summary", "What you owe each supplier, by age band."),
    r("bank-reconciliation", "reconciliations", "Bank reconciliation", "The books' bank balance against the imported statement."),
    r("trial-balance", "taxes", "Trial balance", "Debit and credit balance per account at the period end; totals agree."),
    r("vat-return", "taxes", "UK VAT return", "The 9 boxes for a period, laid out and worded as HMRC's return."),
    r("account-transactions", "transactions", "Account transactions", "Every ledger line in the period, by account."),
    r("accountant-pack", "pack", "Accountant pack", "TB, GL, balance sheet, P&L, aged, VAT returns and detail, contacts and a README, in one zip.", ["zip"]),
    r("xero-manual-journals", "export", "Xero: manual journals", "Manual journal import (CSV).", ["csv"], "xero"),
    r("sage50-audit-trail", "export", "Sage 50: journals (audit trail transactions)", "Audit Trail Transaction template.", ["csv"], "sage50"),
  ],
  favourites: [],
  packages: { xero: "Xero", qbo: "QuickBooks Online", sage50: "Sage 50", "sage-accounting": "Sage Accounting", freeagent: "FreeAgent" },
};

const tb = (code: string, account: string, debit: number | null, credit: number | null) => ({
  cells: { code, account, debit, credit },
  style: "normal" as const,
});

export const sampleTrialBalance: RtExportPreview = {
  doc: {
    id: "trial-balance",
    title: "Trial balance",
    period: "1 Jul 2026 to 30 Sep 2026",
    basis: ["As approved: each entry counts on its own date (invoices when raised, receipts when bought)."],
    sections: [
      {
        title: "Trial balance",
        columns: [
          { key: "code", label: "Code", kind: "text" },
          { key: "account", label: "Account", kind: "text" },
          { key: "debit", label: "Debit", kind: "money" },
          { key: "credit", label: "Credit", kind: "money" },
        ],
        rows: [
          tb("1100", "Debtors", 1_284_000, null),
          tb("1200", "Bank", 2_150_550, null),
          tb("2100", "Creditors", null, 312_000),
          tb("2200", "VAT control", null, 418_550),
          tb("3200", "Profit and loss brought forward", null, 1_934_000),
          tb("4000", "Sales", null, 3_190_000),
          tb("5000", "Materials", 1_598_000, null),
          tb("7100", "Rent", 450_000, null),
          tb("7500", "Office supplies", 372_000, null),
          { cells: { code: "", account: "Total", debit: 5_854_550, credit: 5_854_550 }, style: "total" },
        ],
        note: "Balance-sheet accounts to 30 Sep 2026; profit-and-loss accounts for 1 Jul 2026 to 30 Sep 2026.",
      },
    ],
    warnings: [],
    sample: true,
    generated_at: "2026-10-27T09:00:00Z",
    import_file: null,
  },
  total_rows: [10],
  truncated: false,
  from: "2026-07-01",
  to: "2026-09-30",
  as_of: "2026-09-30",
  mode: null,
  formats: ["csv", "xlsx", "pdf"],
  filenames: { csv: "trial-balance-2026-07-01-to-2026-09-30.csv" },
};
