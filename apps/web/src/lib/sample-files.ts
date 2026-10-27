import { FOLDER } from "./folders";

export type FilesEntry =
  | {
      kind: "folder";
      name: string;
      count: number;
      note?: string;
      collapsed?: boolean;
      badgeWarn?: boolean;
    }
  | { kind: "file"; name: string; note: string };

export const filesTree: FilesEntry[] = [
  { kind: "folder", name: FOLDER.inbox, count: 2 },
  { kind: "folder", name: `${FOLDER.receipts} › 2026-10`, count: 14 },
  { kind: "folder", name: FOLDER.needs_a_look, count: 1, badgeWarn: true },
  { kind: "folder", name: `${FOLDER.sales} › invoices`, count: 6 },
  { kind: "folder", name: FOLDER.bank, count: 1 },
  { kind: "folder", name: FOLDER.payroll, count: 0 },
  { kind: "folder", name: `${FOLDER.vat_returns} › 2026-Q3`, count: 2 },
  { kind: "folder", name: FOLDER.reports, count: 0 },
  { kind: "file", name: "Books.xlsx", note: "rebuilt 17:42" },
  { kind: "file", name: "README.txt", note: "" },
  {
    kind: "folder",
    name: "_System",
    count: 0,
    note: "rules, audit log, ledger events",
    collapsed: true,
  },
];
