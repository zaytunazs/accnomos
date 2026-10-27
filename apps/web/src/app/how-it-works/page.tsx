import Link from "next/link";
import PageHeader from "@/components/PageHeader";

export const metadata = { title: "How it works · Accnomos" };

const loop = [
  {
    title: "Snap",
    body: "Photograph or upload a receipt, or let Outlook intake copy emailed invoices into 00 Inbox. Files are filed by code and never deleted.",
  },
  {
    title: "Read",
    body: "Muse Glimmer 30B reads the document on your own machine (local mode), or Muse Spark reads it with your Meta API key (key mode), into a strict JSON schema: supplier, VAT number, date, lines, net, VAT and total.",
  },
  {
    title: "Check",
    body: "Plain code — never the model — checks the reading: lines add up, totals add up, VAT maths and rates are right, the VAT number has the right shape, it is not a duplicate, it is in pounds, the date is valid and confidence is high enough. A second model then reads the image again without seeing the first answer, and code compares six fields. Anything that fails lands in Needs a look.",
  },
  {
    title: "You approve",
    body: "Every proposal waits on the Review page until you tap Approve or Reject. Nothing reaches your books before that tap — unless you saved an Autopilot rule for that supplier and switched Autopilot on.",
  },
  {
    title: "Code posts",
    body: "Approval writes one immutable, balanced ledger event into _System/Ledger/events, files the document, and rebuilds Books.xlsx from the events. Undo never edits or deletes: it adds a reversing event.",
  },
  {
    title: "VAT",
    body: "The nine VAT boxes are calculated by deterministic code from the events you approved. You then connect HMRC (sandbox), tick the legal declaration and submit — that tap is always yours.",
  },
];

const tree: { name: string; note: string; children?: { name: string; note: string }[] }[] = [
  { name: "00 Inbox", note: "new uploads and Outlook copies wait here" },
  { name: "01 Receipts", note: "filed purchase documents" },
  { name: "02 Sales invoices", note: "sales invoices you raise" },
  { name: "03 Bank statements", note: "imported CSV statements" },
  { name: "04 Needs a look", note: "flagged files, nothing posted" },
  { name: "05 VAT returns/<periodKey>/", note: "return.json and receipt.json per submitted period" },
  { name: "06 Reports", note: "generated reports" },
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
    job: "Turns a spoken Ask question into text, which then goes through the normal grounded Ask. Key mode only; audio is not kept.",
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

      <section aria-labelledby="loop-heading" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="loop-heading" className="text-xl font-extrabold tracking-tight">
          The loop
        </h2>
        <ol className="mt-4 flex flex-col gap-4">
          {loop.map((step, i) => (
            <li key={step.title} className="flex gap-3">
              <span
                aria-hidden="true"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-tint text-[15px] font-extrabold text-teal-dark"
              >
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="text-[15px] font-extrabold">{step.title}</p>
                <p className="mt-0.5 text-[15px] leading-7 text-muted">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="data-heading" className="flex flex-col gap-3">
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

      <section aria-labelledby="models-heading" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
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

      <section aria-labelledby="never-heading" className="rounded-2xl border border-teal bg-white p-5 sm:p-6">
        <h2 id="never-heading" className="text-xl font-extrabold tracking-tight">
          What is never automatic
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          {neverAutomatic.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="next-heading" className="flex flex-wrap gap-2">
        <h2 id="next-heading" className="sr-only">
          Next steps
        </h2>
        <Link
          href="/review"
          className="whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
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
