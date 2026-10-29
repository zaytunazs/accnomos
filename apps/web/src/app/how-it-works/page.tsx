import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import SignInCta from "@/components/SignInCta";
import { FOLDER } from "@/lib/folders";

export const metadata = { title: "How it works · Accnomos" };

const CHECKED = "27 Oct 2026";

interface Feature {
  id: string;
  title: string;
  does: string;
  ai: string;
  code: string;
  gap: string;
}

const features: Feature[] = [
  {
    id: "receipts",
    title: "Receipts: snap, check, approve",
    does: "Photograph or upload a receipt, or drop it in 00 Inbox. It is read, checked against plain rules, and held on the Review page until you tap Approve or Reject. Approval writes one balanced ledger event that is never edited or deleted; Undo adds a reversing event.",
    ai: "The AI reads the document into a strict list: supplier, VAT number, date, lines, net, VAT and total. It also guesses the category.",
    code: "Code checks the reading: lines and totals add up, VAT maths and rates are right, the VAT number has the right shape, it is not a duplicate, it is in pounds, the date is valid and confidence is high enough. A purchase over £250 with no VAT and no VAT number from a supplier the books do not know yet also waits, asking “Is <supplier> VAT-registered?” — the tick teaches “not registered”, a VAT number seen on an approved receipt teaches “registered”, undoing the approval takes the tick back, and Contacts can change the stored answer. Anything that fails waits in Needs a look.",
    gap: "Not verified yet: key-mode reading (Muse Spark) is unit-tested only; HEIC photos are copied but not read; evals use made-up receipts, so real phone photos will score lower.",
  },
  {
    id: "bulk",
    title: "Bulk upload: a whole folder in one go",
    does: "Put any number of files or .zip archives in 01 Bulk upload — and only there; nothing else is ever read in bulk. Zips are unpacked safely (no path tricks, at most 200 files or 200 MB a batch) with nested folders flattened and the folder name kept on each document. Press “Process the bulk folder” on the Review page: every file is read two at a time, you get one summary (“120 receipts, 30 invoices, 6 bank statements, 4 unclear”) to correct row by row, and Confirm all files each one to its normal folder. Processed files move out; failures stay with a reason.",
    ai: "The same reader as single receipts: the model reads each document, code checks the reading.",
    code: "Code unpacks zips entry by entry (absolute paths, parent folders and oversize members are refused), classifies with a two-at-a-time semaphore, and routes each confirmed document through the same filing the Inbox scan uses. When the app opens it lists 01 Bulk upload and 00 Inbox against the filed hashes and names — downloads nothing — behind a thin progress bar, with a small “N new, M changed - Review” badge.",
    gap: "Not verified yet: never run against a real OneDrive with hundreds of files; large batches are untested for time-outs.",
  },
  {
    id: "books",
    title: "Books.xlsx: a copy you can read",
    does: "After every approval, rejection, undo, bank match, invoice, payroll, mileage or job change, the app rebuilds Books.xlsx from the event files. It has 12 sheets (Summary, Ledger, Accounts, VAT, Customers, Suppliers, Bank, Proposals, Jobs, Vehicles, Payroll and a README). It is a read-only copy: do not edit it, it is overwritten.",
    ai: "No AI. The file is built by code from the ledger events.",
    code: "Code reads every event file, works out each sheet, and writes the whole workbook again. If one rebuild fails it is logged and your action still stands.",
    gap: "Not verified yet: the file has never been opened in Excel from a real OneDrive.",
  },
  {
    id: "vat-periods",
    title: "VAT periods and deadlines",
    does: "The VAT page shows a period picker (the current period and the 8 before it) based on the stagger saved in Settings, and works out the nine boxes for the picked period. Home shows the next return date, the payment date and Box 5 so far.",
    ai: "No AI. Dates and boxes are worked out by code.",
    code: "Code picks the period from your stagger (1, 2, 3, a custom start month, or monthly), counts only approved sales and purchases, and truncates boxes 6 to 9 to whole pounds.",
    gap: "Not verified yet: annual accounting and flat-rate schemes are not covered; “submitted” only means our own submission saved a receipt, so a return filed elsewhere still shows as open.",
  },
  {
    id: "hmrc",
    title: "HMRC sandbox submission",
    does: "On the VAT page you connect to HMRC (sandbox), see open obligations, confirm the nine boxes, tick the legal declaration and press Submit. The receipt is saved to 06 VAT returns in your OneDrive. That tap is always yours.",
    ai: "No AI anywhere in this flow.",
    code: "Code sends the nine boxes through the relay, which holds the HMRC client secret and adds the fraud-prevention headers. The relay checks the boxes before forwarding.",
    gap: "Not verified yet: the full browser flow has never been run end to end against HMRC’s sandbox; production filing is not built.",
  },
  {
    id: "ask",
    title: "Ask, typed and spoken",
    does: "Ask answers questions about your books (“how much did I spend with Screwfix?”) and can plan a day (“plan my Thursday”). The web streams the answer: key figures first, then the wording. On the mic button you can speak the question instead of typing it.",
    ai: "The model only writes the words. Key figures and quotes come from a facts pack that code builds from your ledger, and code checks every figure the model writes.",
    code: "Code routes the question to the right books and period, checks each figure against the facts, and replaces any invented or wrong-period figure with the quoted facts.",
    gap: "Not verified yet: voice (Muse Voice Transcribe, with Whisper on our DGX Spark as the fallback) is built to the request format in Meta's own cookbook but has never been called live from our CI; no live mic run on any browser or phone. Bank, payroll, jobs and deadlines are not in the facts pack.",
  },
  {
    id: "actions",
    title: "Actions: words become a card you approve",
    does: "Say or type “send a £100 invoice to JM Trading” or “log 7.5 hours for Sam on Elm Road” and Ask shows a card saying what will happen, to whom, the amount and VAT. Nothing is created, logged or sent until you tap Approve. Change puts the question back; Reject is logged.",
    ai: "The model returns only a structured intent: names as said, amounts as said, dates as said. It never prices a line.",
    code: "Code finds each name in your own lists (fuzzy match, asks “which Hartley?” when unsure), refuses any figure you did not say, sets the VAT code, prices every line in pence, signs the card (15-minute expiry) and runs it exactly once.",
    gap: "Not verified yet: never run against a real model or a real mailbox; without a signing key set, a restart can make a card fail.",
  },
  {
    id: "autopilot",
    title: "Autopilot L1 and L2",
    does: "Level L1 (the default) only proposes: matching cards say they match your rule and you can approve them together. At L2 a receipt from a saved supplier posts without a tap, only when every check passes with no warnings. Every post is logged and has Undo for 30 days.",
    ai: "No AI. The decision is a list of plain checks.",
    code: "Code teaches the rule from your ticked approval (one per supplier), then on each scan requires: same supplier, same VAT number and treatment, total above zero and at most twice the usual, and every check passing with no warning.",
    gap: "Not verified yet: no end-to-end run on real data; the phone never sends the “off” flag, so scans from the phone always run Autopilot when a rule exists.",
  },
  {
    id: "verifier",
    title: "Verifier: a second reading",
    does: "When the first reading passes every code check, a second model reads the same image again with a different prompt, without seeing the first answer. Code compares six fields (supplier, VAT number, date, net, VAT, total). If all six agree the card says so; any disagreement sends the proposal to Needs a look with both readings side by side.",
    ai: "The second model only reads the image again. It never sees the first answer and it never decides.",
    code: "Code compares the six fields (names ignoring case and Ltd/Limited, dates by value, money to the penny, VAT numbers by digits). Nobody picks or merges values: you approve the first reading or reject.",
    gap: "Not verified yet: local mode verifies with Glimmer and key mode with Muse Spark unless the server owner sets a Baseten key; the Baseten model name is unconfirmed and no real Baseten or Meta verifier call has ever been made. Measured catch rate: 0 extra catches in 20 documents, 1 false alarm on a mixed-rate receipt.",
  },
  {
    id: "outlook",
    title: "Outlook intake: emailed bills",
    does: "Switch on Outlook intake in Settings, then tap Check my inbox now. Likely receipts and invoices from the last 14 days are copied into 00 Inbox, deduplicated, with a log in _System/Intake. Mail is never sent, moved, marked read or deleted.",
    ai: "No AI. Plain code filters decide what looks like a receipt.",
    code: "Code reads message dates, senders, subjects and attachments (PDF, JPEG, PNG, HEIC between 10 KB and 25 MB; HEIC saved as JPEG), keeps senders outside your domain with receipt-like words, and skips what was already copied. An email with no attachment is kept as text when a total or VAT line shows an amount.",
    gap: "Not verified yet: never run against a real mailbox or a real phone HEIC; receipts in email text tested on fictional emails only; photos forwarded by a colleague on your own domain are dropped.",
  },
  {
    id: "inbox",
    title: "Inbox triage and to-dos",
    does: "Home’s Inbox card lists the last 7 days of business email (customers, suppliers, HMRC, your accountant), each thread with a one-line summary, a suggested reply and the to-dos in it. Draft in Outlook saves a reply to your Drafts; Add puts a to-do in _System/Todos. Nothing is ever sent.",
    ai: "Your own AI (your key or your local model) suggests the category, summary, reply and to-dos. Email text is passed as untrusted data and the model is told never to follow instructions inside emails.",
    code: "Code reads only the Inbox folder’s sender, subject, date and 255-character preview (never full bodies), drops newsletters, no-reply senders and your own domain, then checks everything the model returns: one of five categories, one line, no links, no figures the emails did not contain, real dates only.",
    gap: "Not verified yet: never run against a real mailbox or model; a failed second Graph call can leave an empty draft; a thread you already answered can still say Reply because Sent Items are not read.",
  },
  {
    id: "bank",
    title: "Bank statements",
    does: "Drop a CSV on the Bank page (Barclays, Starling, Tide, Monzo-style and HSBC/Lloyds paid-in/paid-out layouts are sniffed). The file is saved, the same file twice is a no-op, and each line gets a suggested match to a posted entry. Confirm records which entry the line pays for; unmatched lines can become an expense proposal, a transfer, or be ignored, each undoable.",
    ai: "No AI. Matching is amount (±1p), date (±5 days) and counterparty name.",
    code: "Code parses the CSV, files it by last date and bank, suggests matches, and records your Confirm without posting anything new.",
    gap: "Not verified yet: layouts follow public formats and have not been checked against real exports; part payments are never suggested (one entry paid by two lines finds no match).",
  },
  {
    id: "contacts",
    title: "Contacts",
    does: "Customers and suppliers are built from your ledger (one contact per VAT number, else per name). Each has a statement with a running balance and an Aged balances tab (0–30/31–60/61–90/90+ days from the document date). Edit keeps your changes across Refresh; Import from Outlook fills blank emails and phones.",
    ai: "No AI.",
    code: "Code rebuilds contacts from the event files on each call; only names and details are saved, in _System/Contacts/contacts.json. Money is always worked out again from the events.",
    gap: "Not verified yet: never run against a real OneDrive or Outlook; admin consent on work accounts is untested; a matched bank line counts as full payment, so part payments drop out of Aged balances.",
  },
  {
    id: "invoices",
    title: "Sales invoicing",
    does: "New invoice → draft saved with the next number → preview renders an A4 PDF (your details, logo, VAT summary by rate, bank details) → Send via Outlook only after you tick the confirmation → the sale is posted once, with the sent PDF kept. Reminder drafts, Mark paid and Void (a reversal, never a delete) are on each invoice.",
    ai: "The model only drafts the reminder wording from facts code gives it (never your bank details); code checks every figure. Everything else is code.",
    code: "Code prices each line (net = qty × price, VAT per line, half up to the penny), numbers drafts in order, emails first then marks sent then posts, so a retry never emails twice or posts twice.",
    gap: "Not verified yet: never sent from a real mailbox; a customer credit balance is shown but cannot yet be applied to another invoice or refunded in the app.",
  },
  {
    id: "jobs",
    title: "Jobs, staff and timesheets",
    does: "The Jobs page lists jobs with hours, labour, materials and what is still to invoice. Staff and their cost/charge rates live in Settings. Each job has a timesheet (staff, date, hours in quarter steps, note, billable). Review can tag a purchase to a job on Approve; Invoice these hours prefills an invoice draft.",
    ai: "No AI.",
    code: "Code stores jobs, staff and timesheet entries in _System/Jobs, _System/Staff and _System/Timesheets, tags purchase nets as job materials, and proposes one invoice line per person (hours × charge rate).",
    gap: "Not verified yet: never run against a real OneDrive; “invoiced” value and margin use each person’s current charge rate, so changing a rate restates past jobs.",
  },
  {
    id: "vehicles",
    title: "Vehicles and mileage",
    does: "The Vehicles page lists personal and business-owned vehicles and a mileage log (vehicle, date, from, to, miles in 0.1 steps, purpose). Business miles build up the HMRC approved allowance (cars and vans 45p to 10,000 miles then 25p; motorbikes 24p; bikes 20p). Claim this quarter’s mileage makes one expense proposal per quarter for you to approve in Review.",
    ai: "No AI.",
    code: "Code holds the rate table in one place, works out the allowance per tax year (6 April to 5 April), locks claimed journeys until the claim is undone, and tags fuel receipts to your only active business vehicle at scan time.",
    gap: "Not verified yet: never run against a real OneDrive; the fuel scale charge is shown as “ask your accountant” text and is not calculated.",
  },
  {
    id: "payroll",
    title: "Pay runs (estimates only)",
    does: "Payroll prepares a month’s pay run from timesheets (hours × each person’s rate), shows estimated PAYE, employee NI, net pay and employer NI, exports a CSV for your payroll provider to 05 Payroll, and on Confirm posts the provider’s actual gross and employer NI as two balanced adjustments. Accnomos does not run payroll, file RTI or pay HMRC.",
    ai: "No AI.",
    code: "Code works out the estimates from one 2026–27 rate table, saves the run in _System/Payroll/runs, labels every figure an estimate, and only posts the actuals you type in.",
    gap: "Not verified yet: rates were checked against GOV.UK by hand on 27 Oct 2026 with no test pinning them — re-check each April. Monthly pay only, tax code 1257L month-1 basis, England/NI rates, NI category A; no loans, pensions, statutory pay, benefits or salary sacrifice.",
  },
  {
    id: "planner",
    title: "Day planner",
    does: "Plan today on Home, Plan a day with these jobs on Jobs, or “plan my Thursday” in Ask proposes a working day from your Outlook calendar, open jobs and any VAT return due within 7 days. Apply writes the new items as [Accnomos] events. Nothing is written before Apply.",
    ai: "The model only writes the plain-English rationale from the finished plan. Code rejects any rationale quoting a time or figure not in the plan and writes its own instead.",
    code: "Code groups open jobs by postcode district, orders districts so the route sweeps, allows 2 h visits (or the job’s visit length), 30/60 min travel, lunch and an admin hour, never overlapping existing events, in Europe/London on the quarter hour.",
    gap: "Not verified yet: never run against a real calendar; travel times are rules of thumb, not routing; only the default calendar; first-time calendar consent loses the plan (plan again and tap Apply again).",
  },
  {
    id: "files",
    title: "Files: your folder, shown as is",
    does: "The Files page lists the real books folder from OneDrive (00 to 07 with file counts, plus _System collapsed), with Open links and Rebuild Books.xlsx on demand. Signed out it shows the sample tree.",
    ai: "No AI.",
    code: "Code lists the folder through Graph and rebuilds the spreadsheet from the events when asked.",
    gap: "Not verified yet: never checked against a real OneDrive; a folder’s file count can include nested folders.",
  },
  {
    id: "android",
    title: "Android app",
    does: "The phone app signs in, captures receipts, and covers Review (approve, edit, reject, Autopilot undo), Ask with mic and action cards, Home, VAT with a period picker, and Files, Contacts, Invoices, Jobs, Vehicles, Bank and read-only Payroll under More. There is no HMRC filing on the phone.",
    ai: "Same split as the web: the AI reads documents and writes words; code checks and posts.",
    code: "The phone calls the same runtime routes as the web.",
    gap: "Not verified yet: the Flutter app has never been built, analysed or tested in this pass; the Play release signing hash may not be registered so sign-in can fail; the VAT stagger is saved but never sent, so VAT uses calendar quarters; the Meta key is not in secure storage.",
  },
];

const faqs: { q: string; a: string }[] = [
  {
    q: "Where is my data?",
    a: "In your own OneDrive, in a folder called Accnomos (Apps/Accnomos on a personal account, /Accnomos on a work account). There is no Accnomos database and we keep no copy. Open the folder any time: receipts by month, invoices, bank statements, VAT returns, Books.xlsx and the _System ledger underneath.",
  },
  {
    q: "Can it file my VAT by itself?",
    a: "No. The nine boxes are worked out by code, but nothing is sent until you tick the legal declaration and press Submit. Filing is sandbox only: no production filing is built.",
  },
  {
    q: "What if the AI is wrong?",
    a: "Three things stand between a wrong reading and your books: plain code checks (maths, VAT, duplicates, currency, dates, confidence), a second independent reading that code compares field by field, and your Approve tap. Anything unsure waits in Needs a look with the reason shown.",
  },
  {
    q: "When is a missing VAT number questioned?",
    a: "When your business is VAT-registered and a purchase over £250 shows no VAT and no VAT number from a supplier the books do not know yet. The card asks “Is <supplier> VAT-registered? Over £250 they should give a VAT invoice”, with a tick for “isn't VAT-registered”. The tick teaches “not registered”; a VAT number seen on an approved receipt teaches “registered”; undoing the approval takes the tick back; you can change the stored answer any time on Contacts.",
  },
  {
    q: "What does the verifier do?",
    a: "It reads the same photo again with a different prompt, without seeing the first answer. Code compares supplier, VAT number, date, net, VAT and total. All six must agree or the proposal waits for you with both readings side by side. It never picks or merges values.",
  },
  {
    q: "Why do I need a Meta key or a local model?",
    a: "The reading and answering models run either on a machine you control (Muse Glimmer on Ollama, local mode) or through a Meta API key you paste in (key mode). In local mode documents go only to Ollama. In key mode with no key header, the server’s own key is used as a fallback.",
  },
  {
    q: "Can I delete everything?",
    a: "Yes. Delete the Accnomos folder in your OneDrive and sign out. Because we hold no copy, that removes everything. Undo inside the app never deletes: it adds a reversing entry so the trail stays complete.",
  },
  {
    q: "What does Autopilot post on its own?",
    a: "Only a receipt matching a rule you saved (same supplier, VAT number and treatment, total at most twice the usual) with every code check passing and no warnings, verifier agreeing, at level L2. L1 (the default) only proposes. It never invents rules and never posts sales, mileage or anything unsure.",
  },
  {
    q: "Does it ever send email by itself?",
    a: "No. Invoices, reminders and inbox replies are drafts until you confirm each one in turn: invoice sending needs your ticked confirmation, replies wait in Outlook Drafts for you to press Send, and triage never sends at all.",
  },
  {
    q: "What does “estimate” mean on Payroll?",
    a: "The tax and NI figures are a rough guide for monthly pay under tax code 1257L (month-1 basis, England/NI rates, NI category A). Your payroll provider works out the real amounts; Confirm posts the actuals you type in, not the estimate. Accnomos never files RTI or pays HMRC.",
  },
  {
    q: "What can it see in my mailbox and calendar?",
    a: "Only what each feature asks for, when you first use it: Outlook intake and triage read the Inbox list (triage sees sender, subject, date and a 255-character preview, never full bodies); drafts need Mail.ReadWrite; sending invoices needs Mail.Send; planning reads the calendar first and only writes on Apply. Details are in the privacy policy’s data map.",
  },
  {
    q: "What has not been tested on real services?",
    a: "Almost everything beyond one hand-run receipt flow: key-mode models, the Baseten verifier, SAM crop, voice, HMRC end to end, real OneDrive, mailbox, calendar and phone runs are tested on fakes or not yet run. The full list is in docs/HONESTY.md and each section above says what is not verified yet.",
  },
  {
    q: "How do I check this page against the code?",
    a: "Each section names the behaviour; the contracts live in docs/ARCHITECTURE.md, AUTOPILOT.md, ACTIONS.md, INBOX.md, PLANNER.md and HONESTY.md, tested by services/runtime/tests and the Playwright suite (pnpm run e2e). This page was last checked against main on 27 Oct 2026.",
  },
];

const tree: { name: string; note: string; children?: { name: string; note: string }[] }[] = [
  { name: FOLDER.inbox, note: "new uploads and Outlook copies wait here" },
  { name: FOLDER.receipts, note: "filed purchase documents, by month" },
  { name: FOLDER.needs_a_look, note: "flagged files, nothing posted" },
  { name: `${FOLDER.sales}/`, note: "scanned sales documents; invoices/ holds the invoices you raise, invoices/sent/ what was emailed" },
  { name: FOLDER.bank, note: "imported CSV statements" },
  { name: FOLDER.payroll, note: "pay run exports for your payroll provider" },
  { name: `${FOLDER.vat_returns}/<periodKey>/`, note: "return.json and receipt.json per submitted period" },
  { name: FOLDER.reports, note: "generated reports" },
  { name: "Books.xlsx", note: "read-only projection, rebuilt after every approval — do not edit" },
  { name: "README.txt", note: "says what the folder is" },
  {
    name: "_System/",
    note: "app data — rules, audit trail and the books themselves",
    children: [
      { name: "Ledger/events/<yyyy-mm>/", note: "the books: one balanced journal file per approval" },
      { name: "proposals/ and docs/", note: "proposals with their decisions, one record per document" },
      { name: "audit/ and audit/autopilot/", note: "append-only trail of who did what" },
      { name: "Rules/rules.json", note: "the Autopilot rules you saved, one per supplier" },
      { name: "Contacts, Jobs, Staff, Timesheets, Vehicles, Mileage, bank, Intake", note: "working data — money is always recomputed from the events" },
    ],
  },
];

const models = [
  {
    name: "Muse Glimmer 30B",
    job: "Reads receipts and invoices, categorises them, and answers Ask in local mode. Also does the second reading (Verifier) in local mode, so the document never leaves your machine.",
  },
  {
    name: "Muse Spark",
    job: "Same reading and answering jobs when you bring your own Meta API key (key mode). Stands in as the Verifier when no Baseten key is set.",
  },
  {
    name: "Muse Spark Open (Baseten, optional)",
    job: "Independent second reading in key mode, only if the server owner set a key. Unit-tested only; the model name is unconfirmed.",
  },
  {
    name: "Muse Voice Transcribe",
    job: "Turns a spoken Ask question or instruction into text, which then goes through the normal grounded Ask. Uses your Meta key or the server's; Whisper on our DGX Spark takes over if it fails, and each answer says which one heard it. Audio is not kept.",
  },
  {
    name: "SAM 3.1",
    job: "Finds and crops the receipt inside a messy phone photo — only when switched on. Off by default; plain code crop is the default.",
  },
  {
    name: "Muse Image",
    job: "Made the brand artwork at build time. It is not part of the running product.",
  },
];

const neverAutomatic = [
  "Posting to your books — every entry waits for your Approve, except Autopilot L2 postings that match a rule you saved.",
  "Creating an Autopilot rule — only your ticked approval writes one, one per supplier.",
  "Sending a VAT return to HMRC — nothing is sent until you tick the legal declaration and press Submit.",
  "Sending or chasing an invoice email — drafts only; you read, edit and confirm each one.",
  "Deleting or editing a ledger event — corrections are new reversing events, never edits.",
  "Auto-approving sales, mileage claims, or anything with a failed or warned check — these always wait for you.",
  "Inventing numbers — Ask answers are computed by code from your ledger; the model only writes the words, and every figure is checked against the facts.",
];

function FolderTree() {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-white">
      <ul className="min-w-[300px] p-4 font-mono text-[13px] leading-7">
        <li className="font-bold">OneDrive › Apps › Accnomos</li>
        <li className="text-muted">Work accounts use /Accnomos instead.</li>
        {tree.map((entry) => (
          <li key={entry.name} className="mt-1">
            <span className="font-bold text-ink">├── {entry.name}</span>{" "}
            <span className="font-sans text-muted">— {entry.note}</span>
            {entry.children && (
              <ul className="ml-6 border-l border-border pl-3">
                {entry.children.map((child) => (
                  <li key={child.name}>
                    <span className="font-bold text-ink">{child.name}</span>{" "}
                    <span className="font-sans text-muted">— {child.note}</span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function HowItWorksPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="How it works"
        description="Snap a receipt, check what the AI read, approve it, and code does the books. Your data stays in your OneDrive throughout."
      />
      <p className="text-sm text-muted">Last checked against main on {CHECKED}.</p>

      <nav aria-label="Contents" className="rounded-2xl border border-border bg-white p-5">
        <h2 className="text-lg font-extrabold tracking-tight">Contents</h2>
        <ul className="mt-2 grid grid-cols-1 gap-1 text-[15px] min-[560px]:grid-cols-2">
          {features.map((f) => (
            <li key={f.id}>
              <Link href={`#${f.id}`} className="font-semibold text-teal-dark underline hover:text-teal">
                {f.title}
              </Link>
            </li>
          ))}
          <li>
            <Link href="#data" className="font-semibold text-teal-dark underline hover:text-teal">
              Where your data lives
            </Link>
          </li>
          <li>
            <Link href="#models" className="font-semibold text-teal-dark underline hover:text-teal">
              Which model does what
            </Link>
          </li>
          <li>
            <Link href="#never" className="font-semibold text-teal-dark underline hover:text-teal">
              What is never automatic
            </Link>
          </li>
          <li>
            <Link href="#faq" className="font-semibold text-teal-dark underline hover:text-teal">
              FAQ
            </Link>
          </li>
        </ul>
      </nav>

      {features.map((f) => (
        <section key={f.id} id={f.id} aria-labelledby={`${f.id}-heading`} className="rounded-2xl border border-border bg-white p-5 sm:p-6 scroll-mt-24">
          <h2 id={`${f.id}-heading`} className="text-xl font-extrabold tracking-tight">
            {f.title}
          </h2>
          <p className="mt-2 text-[15px] leading-7">{f.does}</p>
          <ul className="mt-3 space-y-2 text-[15px] leading-7">
            <li>
              <span className="font-bold">The AI: </span>
              <span className="text-muted">{f.ai}</span>
            </li>
            <li>
              <span className="font-bold">The code: </span>
              <span className="text-muted">{f.code}</span>
            </li>
            <li>
              <span className="font-bold">Not verified yet: </span>
              <span className="text-muted">{f.gap}</span>
            </li>
          </ul>
        </section>
      ))}

      <section id="data" aria-labelledby="data-heading" className="flex flex-col gap-3 scroll-mt-24">
        <div>
          <h2 id="data-heading" className="text-xl font-extrabold tracking-tight">
            Where your data lives
          </h2>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            There is no Accnomos database. Your books are files in your own OneDrive folder, readable
            whether or not our services are running. Accnomos has no copy — delete the folder and it is gone.
          </p>
        </div>
        <FolderTree />
      </section>

      <section id="models" aria-labelledby="models-heading" className="rounded-2xl border border-border bg-white p-5 sm:p-6 scroll-mt-24">
        <h2 id="models-heading" className="text-xl font-extrabold tracking-tight">
          Which model does what
        </h2>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          There is no separate LLM reviewer in the pipeline: the “Why” line on each proposal card is
          composed by code (“Checker, code”), and a model only writes words in Ask.
        </p>
        <ul className="mt-4 flex flex-col gap-3">
          {models.map((model) => (
            <li key={model.name} className="rounded-xl bg-ground p-4">
              <p className="text-[15px] font-extrabold">{model.name}</p>
              <p className="mt-0.5 text-[14px] leading-6 text-muted">{model.job}</p>
            </li>
          ))}
        </ul>
      </section>

      <section id="never" aria-labelledby="never-heading" className="rounded-2xl border border-teal bg-white p-5 sm:p-6 scroll-mt-24">
        <h2 id="never-heading" className="text-xl font-extrabold tracking-tight">
          What is never automatic
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          {neverAutomatic.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section id="faq" aria-labelledby="faq-heading" className="rounded-2xl border border-border bg-white p-5 sm:p-6 scroll-mt-24">
        <h2 id="faq-heading" className="text-xl font-extrabold tracking-tight">
          FAQ
        </h2>
        <div className="mt-2 flex flex-col gap-5">
          {faqs.map((f) => (
            <div key={f.q}>
              <h3 className="text-[16px] font-extrabold">{f.q}</h3>
              <p className="mt-1 text-[15px] leading-7 text-muted">{f.a}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="next-heading" className="flex flex-wrap gap-2">
        <h2 id="next-heading" className="sr-only">
          Next steps
        </h2>
        <SignInCta className="whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark" />
        <Link
          href="/review"
          className="whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-ink hover:bg-ground"
        >
          See the demo books
        </Link>
        <Link
          href="/privacy"
          className="whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-ink hover:bg-ground"
        >
          Data map in the privacy policy
        </Link>
      </section>
    </div>
  );
}
