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
