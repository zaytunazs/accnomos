export type Tile = {
  label: string;
  value: string;
  sub: string;
  tone?: "default" | "amber" | "warn";
  href?: string; // the sub line links here
  extra?: { label: string; value: string }; // a second line under the figure (PayPal (books) beside the bank)
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
];

/** The sample's "what needs attention" counts (GET /books/dashboard `attention`), as on Home for the fictional Bramblewood books. */
export const sampleAttention = { proposed: 3, needs_a_look: 0, unmatched_bank_lines: 2, overdue_invoices: 1, total: 6 };

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
    actor: "AI · local",
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
  // The business snapshot: a company's year runs from 1 January (no year end saved). Turnover and expenses for
  // Jan–Oct are the trend's months added up; the changes are worked out from last year's figures below.
  snapshot: {
    start: "2026-01-01",
    end: "2026-10-27",
    period_label: "1 Jan – 27 Oct 2026",
    year_start_rule: "the calendar year (no year end is saved for these books)",
    basis: "accrual from approved entries",
    accounting_basis: "traditional",
    turnover_pence: 14862000,
    expenses_pence: 10134000,
    net_profit_pence: 4728000,
    last_year_start: "2025-01-01",
    last_year_end: "2025-10-27",
    last_year_label: "1 Jan – 27 Oct 2025",
    last_year: { turnover_pence: 13270000, expenses_pence: 9410000, net_profit_pence: 3860000 },
    change_pct: { turnover: 12, expenses: 8, net_profit: 22 },
    vat_position: { label: "Jul–Sep 2026", amount_pence: 214000, direction: "pay", due: "2026-11-07", days_left: 11, estimate: false },
    entries: 412,
  },
  trend: {
    sample: true,
    months: [
      { month: "2025-11", label: "Nov 2025", start: "2025-11-01", end: "2025-11-30", sales_pence: 1310000, purchases_pence: 940000, net_pence: 370000 },
      { month: "2025-12", label: "Dec 2025", start: "2025-12-01", end: "2025-12-31", sales_pence: 1020000, purchases_pence: 980000, net_pence: 40000 },
      { month: "2026-01", label: "Jan 2026", start: "2026-01-01", end: "2026-01-31", sales_pence: 1240000, purchases_pence: 910000, net_pence: 330000 },
      { month: "2026-02", label: "Feb 2026", start: "2026-02-01", end: "2026-02-28", sales_pence: 1180000, purchases_pence: 870000, net_pence: 310000 },
      { month: "2026-03", label: "Mar 2026", start: "2026-03-01", end: "2026-03-31", sales_pence: 1420000, purchases_pence: 990000, net_pence: 430000 },
      { month: "2026-04", label: "Apr 2026", start: "2026-04-01", end: "2026-04-30", sales_pence: 1510000, purchases_pence: 1040000, net_pence: 470000 },
      { month: "2026-05", label: "May 2026", start: "2026-05-01", end: "2026-05-31", sales_pence: 1630000, purchases_pence: 1120000, net_pence: 510000 },
      { month: "2026-06", label: "Jun 2026", start: "2026-06-01", end: "2026-06-30", sales_pence: 1580000, purchases_pence: 1060000, net_pence: 520000 },
      { month: "2026-07", label: "Jul 2026", start: "2026-07-01", end: "2026-07-31", sales_pence: 1720000, purchases_pence: 1180000, net_pence: 540000 },
      { month: "2026-08", label: "Aug 2026", start: "2026-08-01", end: "2026-08-31", sales_pence: 1490000, purchases_pence: 1030000, net_pence: 460000 },
      { month: "2026-09", label: "Sep 2026", start: "2026-09-01", end: "2026-09-30", sales_pence: 1650000, purchases_pence: 1090000, net_pence: 560000 },
      { month: "2026-10", label: "Oct 2026", start: "2026-10-01", end: "2026-10-31", sales_pence: 1442000, purchases_pence: 844000, net_pence: 598000 },
    ],
  },
  cash_points: {
    as_of: "2026-10-27",
    opening_balance_pence: 1248000,
    points: [
      { days: 0, date: "2026-10-27", balance_pence: 1248000 },
      { days: 7, date: "2026-11-03", balance_pence: 1410000 },
      { days: 14, date: "2026-11-10", balance_pence: 1196000 },
      { days: 21, date: "2026-11-17", balance_pence: 1280000 },
      { days: 28, date: "2026-11-24", balance_pence: 940000 },
      { days: 30, date: "2026-11-26", balance_pence: 940000 },
      { days: 35, date: "2026-12-01", balance_pence: 690000 },
      { days: 42, date: "2026-12-08", balance_pence: 430000 },
      { days: 48, date: "2026-12-14", balance_pence: 124000 },
      { days: 49, date: "2026-12-15", balance_pence: 260000 },
      { days: 56, date: "2026-12-22", balance_pence: 510000 },
      { days: 60, date: "2026-12-26", balance_pence: 510000 },
      { days: 63, date: "2026-12-29", balance_pence: 380000 },
      { days: 70, date: "2027-01-05", balance_pence: 790000 },
      { days: 77, date: "2027-01-12", balance_pence: 1040000 },
      { days: 84, date: "2027-01-19", balance_pence: 1120000 },
      { days: 90, date: "2027-01-25", balance_pence: 1205000 },
    ],
    lowest_balance_pence: 124000,
    lowest_on: "2026-12-14",
    below_zero_on: null,
  },
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
    summary_md: "3 things need you now, 2 coming up.",
    model: "code",
    fallback_reason: "Sample books: code wrote this.",
    facts: {},
    items: [
      {
        id: "overdue_invoices",
        priority: 1,
        tone: "negative",
        title: "1 invoice overdue: £3,250.00",
        detail: "Customers are late paying; a reminder usually helps.",
        action: { label: "Chase", route: "/invoices?filter=overdue" },
      },
      {
        id: "review",
        priority: 1,
        tone: "warning",
        title: "3 items waiting for your approval",
        detail: null,
        action: { label: "Review", route: "/review" },
      },
      {
        id: "payroll_due",
        priority: 1,
        tone: "warning",
        title: "Pay run 2026-10 to confirm due 31 Oct",
        detail: "Due 31 Oct 2026, in 4 days.",
        action: { label: "Open", route: "/payroll" },
      },
      {
        id: "vat_due",
        priority: 2,
        tone: "warning",
        title: "VAT return Jul–Sep 2026 due 7 Nov",
        detail: "Due 7 Nov 2026, in 11 days.",
        action: { label: "File it", route: "/vat" },
      },
      {
        id: "bank_unmatched",
        priority: 2,
        tone: "warning",
        title: "2 bank lines to match",
        detail: "Matching keeps your cash figure and VAT right.",
        action: { label: "Match", route: "/bank/reconcile" },
      },
      {
        id: "trend",
        priority: 3,
        tone: "positive",
        title: "Turnover £148,620.00 this year, up 12%",
        detail: "1 Jan – 27 Oct 2026, against the same dates last year.",
        action: null,
      },
    ],
  },
  unavailable: [],
};
