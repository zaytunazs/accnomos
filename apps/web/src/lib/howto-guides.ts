/**
 * The how-to guides in docs/howto/ (read on GitHub), shared by the landing page and How it works. Each thumbnail is a
 * screenshot from the guide, from the demo sandbox's fictional sample books, saved as public/howto/<file>.webp
 * (640 × 400). When a guide is added or renamed, change it here and in docs/howto/README.md.
 */
export const GUIDES_URL = "https://github.com/zaytunazs/accnomos/blob/main/docs/howto";

export interface HowtoGuide {
  file: string;
  title: string;
  /** One line: what the guide gets you to do. */
  summary: string;
  /** Who it is for (How it works lists this). */
  who: string;
  /** The thumbnail's description. */
  alt: string;
  /** Shown on the landing page (the rest are one click away). */
  featured?: boolean;
}

export const GUIDES: HowtoGuide[] = [
  {
    file: "connect-books",
    title: "Try the demo or connect your books",
    summary: "Open the sample books with no sign-in, or sign in with Microsoft and read your Home summary.",
    who: "Opening Accnomos for the first time",
    alt: "Home in the demo: Your summary lists overdue invoices, items to approve and the VAT deadline, each with a button to act on it.",
    featured: true,
  },
  {
    file: "review-approve",
    title: "Review and approve",
    summary: "Check each reading against the document, then approve, edit or reject. Nothing posts on its own.",
    who: "Clearing the Review queue",
    alt: "Review: a proposed entry for a fictional supplier with the checks, the second reading and the Approve button.",
    featured: true,
  },
  {
    file: "vat-return",
    title: "Do a VAT return",
    summary: "Nine boxes worked out by code, checked against the entries, then the sandbox HMRC flow.",
    who: "VAT-registered and filing through MTD",
    alt: "The VAT return for Jul–Sep 2026 with the nine boxes and the number of entries behind each.",
    featured: true,
  },
  {
    file: "voice-chat",
    title: "Talk to Accnomos, by voice or chat",
    summary: "Ask in plain words from any page, go hands-free, and approve what it proposes.",
    who: "Asking in plain words, typed or spoken",
    alt: "The Talk to Accnomos panel answering a VAT question with the figures and the ledger files they came from.",
    featured: true,
  },
  {
    file: "goals",
    title: "Set goals and track progress",
    summary: "Savings, spending limits and sales targets, measured against your own books.",
    who: "Anyone with a target for the business or the household",
    alt: "Goals & progress: three fictional goals, each with its progress bar and whether it is on track.",
    featured: true,
  },
  {
    file: "calendar",
    title: "Calendar and deadlines",
    summary: "Put tax deadlines in your Outlook calendar, one at a time or all automatically, with clash warnings.",
    who: "Keeping VAT, payroll and Income Tax dates in view",
    alt: "Calendar: Add all deadlines to my calendar automatically, with the VAT return added as an all-day event.",
    featured: true,
  },
  {
    file: "notes-tasks",
    title: "Notes, to-dos and events by voice",
    summary: "Say “take a note” or “add a meeting” and approve the card it makes.",
    who: "Capturing jobs and reminders on the go",
    alt: "A proposed note card, Ring the scaffolder about Friday, with Approve, Change and Reject.",
  },
  {
    file: "personal-finances",
    title: "Personal finances",
    summary: "Budgets, regular bills and savings goals from your own bank statements.",
    who: "A household, or an owner keeping personal money apart",
    alt: "A fictional household's Home: this month's money in and out, budgets over and bills due.",
  },
  {
    file: "import-contacts",
    title: "Import contacts",
    summary: "Bring in customers and suppliers from Outlook, your phone or people who email you, and merge duplicates.",
    who: "Setting up customers and suppliers",
    alt: "Import contacts from Outlook: fictional businesses ticked, each set as a customer or supplier.",
  },
  {
    file: "add-mailbox",
    title: "Collect receipts by email",
    summary: "Watch a mailbox for supplier receipts; mail is only read, never sent, moved or deleted.",
    who: "Collecting supplier receipts by email",
    alt: "Settings, Automation: Outlook intake and Email intake with the mailbox to watch.",
  },
  {
    file: "reconcile-bank",
    title: "Reconcile bank lines",
    summary: "Import a statement, confirm the suggested matches and deal with the rest.",
    who: "Matching a statement against the books",
    alt: "Bank: the reconciled-to date, matched lines and suggested matches to confirm.",
  },
  {
    file: "income-tax-update",
    title: "Income Tax quarterly update",
    summary: "Turn on self-employment or landlord mode and practise the MTD Income Tax flow in the sandbox.",
    who: "Sole traders and landlords sending MTD updates",
    alt: "Self-employment (MTD Income Tax) with the sandbox HMRC connect button.",
  },
  {
    file: "payroll-paye",
    title: "Run payroll and file with Basic PAYE Tools",
    summary: "Add employees, calculate a pay run and download the FPS and EPS files to file yourself.",
    who: "Employers running a pay run",
    alt: "Payroll: a calculated pay run for a fictional employee with gross, tax, NI and net pay.",
  },
  {
    file: "invite-accountant",
    title: "Invite your accountant",
    summary: "Share your books folder, view only or view and edit, and see what they did in the audit trail.",
    who: "Giving your accountant access",
    alt: "Settings, Your accountant: the invite form with an email address and the access choice.",
  },
  {
    file: "export-accountant",
    title: "Export for your accountant",
    summary: "Reports, the ledger and the VAT return as files, plus a full export of your data.",
    who: "Sending a period's records away",
    alt: "Reports & exports: financial statements, taxes and balances, ready to preview or save.",
  },
];
