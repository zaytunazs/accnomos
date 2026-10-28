export type Tile = {
  label: string;
  value: string;
  sub: string;
  tone?: "default" | "amber" | "warn";
  href?: string; // the sub line links here
};

export const tiles: Tile[] = [
  {
    label: "Cash in bank",
    value: "£12,480",
    sub: "Reconciled to 24 Oct",
  },
  {
    label: "Owed to you",
    value: "£3,250",
    sub: "1 invoice 12 days overdue",
    tone: "amber",
  },
  {
    label: "Owed by you",
    value: "£1,140",
    sub: "2 unpaid bills, oldest 18 days",
  },
  {
    label: "VAT estimate · Q3",
    value: "£2,140",
    sub: "Calculated by code from approved entries",
  },
  {
    label: "Needs a look",
    value: "3",
    sub: "Review now →",
    tone: "warn",
    href: "/review",
  },
];

export type Deadline = {
  month: string;
  day: string;
  title: string;
  sub: string;
  tinted?: boolean;
};

export const deadlines: Deadline[] = [
  {
    month: "NOV",
    day: "7",
    title: "VAT return 2026-Q3 due",
    sub: "12 days · on your Outlook calendar",
    tinted: true,
  },
  {
    month: "NOV",
    day: "7",
    title: "VAT payment due",
    sub: "Estimated £2,140",
  },
  {
    month: "JAN",
    day: "31",
    title: "Self Assessment",
    sub: "Director's return",
  },
];

export type ActivityItem = {
  time: string;
  text: string;
  actor: string;
  dot: "teal" | "amber";
};

export const activity: ActivityItem[] = [
  {
    time: "17:42",
    text: "Imported Screwfix invoice £184.20 from Outlook, filed to 01 Receipts/2026-10, proposed entry",
    actor: "Glimmer · local",
    dot: "teal",
  },
  {
    time: "17:41",
    text: "Moved Travis Perkins receipt to 02 Needs a look — possible duplicate of 14 Oct",
    actor: "Checker · code",
    dot: "amber",
  },
  {
    time: "09:10",
    text: "Matched 6 bank lines to approved entries; drafted chaser for INV-0042 (in Outlook Drafts, not sent)",
    actor: "Reconciler · Spark",
    dot: "teal",
  },
];

/** GET /books/home for the fictional Bramblewood sample (signed out, on /try): a VAT-registered company. Every
 *  figure here is fictional; the summary is the code-written one the runtime would give for these facts. */
export const sampleOverview: import("./runtime").RtHome = {
  today: "2026-10-27",
  kind: "company",
  features: ["vat", "invoices", "payroll"],
  money: {
    this_month: { label: "October 2026", start: "2026-10-01", end: "2026-10-27", money_in_pence: 1842000, money_out_pence: 1126050, lines: 41 },
    last_month: { label: "September 2026", start: "2026-09-01", end: "2026-09-30", money_in_pence: 1610000, money_out_pence: 1385500, lines: 52 },
  },
  week: { start: "2026-10-21", end: "2026-10-27", money_in_pence: 412000, money_out_pence: 268040, approved: 9, proposed: 3 },
  aged: {
    debtors: { total_pence: 325000, overdue_pence: 325000, buckets: { current: 0, "0-30": 325000, "31-60": 0, "61-90": 0, "90+": 0 }, documents: 1 },
    creditors: { total_pence: 114000, overdue_pence: 0, buckets: { current: 114000, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0 }, documents: 2 },
  },
  itsa: null,
  payroll: {
    employees: 2,
    draft_period: "2026-10",
    draft_pay_date: "2026-10-31",
    last_confirmed_period: "2026-09",
    last_pay_date: "2026-09-30",
    next_period: "2026-10",
  },
  cis: null,
  property: null,
  deadlines: [
    { key: "payroll", title: "Pay run 2026-10 to confirm", due: "2026-10-31", days_left: 4, href: "/payroll", source_url: null },
    { key: "vat", title: "VAT return Jul–Sep 2026", due: "2026-11-07", days_left: 11, href: "/vat", source_url: null },
  ],
  summary: {
    summary_md:
      "You had £12,480.00 in the bank on 24 Oct 2026. October 2026 so far, £18,420.00 came in and £11,260.50 went out, " +
      "against £16,100.00 in and £13,855.00 out in September 2026. To do: 3 items waiting in Review and 1 invoice " +
      "overdue (£3,250.00). Next deadline: Pay run 2026-10 to confirm, due 31 Oct 2026 (in 4 days).",
    model: "code",
    fallback_reason: "Sample books: code wrote this.",
    facts: {},
  },
  unavailable: [],
};
