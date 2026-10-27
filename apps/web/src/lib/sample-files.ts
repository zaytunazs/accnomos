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
  { kind: "folder", name: "00 Inbox", count: 2 },
  { kind: "folder", name: "01 Receipts › 2026-10", count: 14 },
  { kind: "folder", name: "02 Sales invoices", count: 6 },
  { kind: "folder", name: "03 Bank statements", count: 1 },
  { kind: "folder", name: "04 Needs a look", count: 1, badgeWarn: true },
  { kind: "folder", name: "05 VAT returns › 2026-Q3", count: 2 },
  { kind: "folder", name: "06 Reports", count: 0 },
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
