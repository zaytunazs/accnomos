import Link from "next/link";
import TryDemo from "@/components/demo/TryDemo";

export const metadata = { title: "Your demo · Accnomos", robots: { index: false, follow: false } };

/**
 * The demo guide (lib/public-site.ts DEMO_GUIDE): where "Try the demo" lands, inside a demo sandbox (lib/demo.ts) with
 * the demo bar. Written for the person who will keep their own books here. The hackathon's notes on what is real
 * and how to run the code are the separate /judges page, which links back to this tour.
 */
const steps: { title: string; href: string; body: string }[] = [
  {
    title: "Open a receipt that is waiting for you",
    href: "/review",
    body: "Six documents are in Review. Open one and see what the AI read from it, the checks that were run on it, and the entry it would put in your books. Two of them need a look: an invoice in euros, and a VAT number that is not quite right.",
  },
  {
    title: "Approve it, or change it first",
    href: "/review",
    body: "Nothing goes into your books until you say so. Approve a receipt and the entry lands in the ledger and in Books.xlsx; if you change your mind, undo it and a reversing entry is posted. Add a receipt of your own with the Add a receipt button and watch it read.",
  },
  {
    title: "Ask, by typing or by talking",
    href: "/ask",
    body: "Ask “How much VAT do I owe this quarter?” or “Who owes me the most?”, or press Talk to Accnomos and say it. The figures come from your books, worked out by code; the AI only explains them. Ask it to send a £100 invoice to Hartwell Property Maintenance and it drafts one that waits for your Approve.",
  },
  {
    title: "Raise an invoice",
    href: "/invoices",
    body: "Invoices with VAT, due dates and who has paid. Send one: in the demo nothing is actually emailed, and the page says so (“Sent (demo — not actually sent)”).",
  },
  {
    title: "Match the bank",
    href: "/bank",
    body: "Two imported statements matched against the books, bank rules that code the regular lines for you, and what is still to match. Connect the test bank to see a live feed come in, labelled as the sandbox it is.",
  },
  {
    title: "File a VAT return to HMRC’s test service",
    href: "/vat",
    body: "The nine boxes, worked out by code from the entries you approved, with the entries behind each box. Connect to HMRC’s sandbox with a test user made for this demo, submit, and get HMRC’s own receipt back. No real tax is filed.",
  },
  {
    title: "Set a goal and see how it is going",
    href: "/goals",
    body: "Three business goals sized from these books: this month’s sales, spending in the busiest purchase category, and a VAT pot. Each is tracked against the ledger, with a suggestion when one slips.",
  },
  {
    title: "Reports and contacts",
    href: "/reports",
    body: "Profit and loss, aged debtors and creditors, the VAT summary and the trend over six months. Contacts are built from the ledger: who owes what, and which suppliers are not VAT-registered.",
  },
];

export default function DemoPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <p className="text-xs font-extrabold uppercase tracking-[0.08em] text-teal-dark">Demo</p>
        <h1 className="text-3xl font-extrabold leading-tight tracking-tight">Your demo of Accnomos</h1>
        <p className="text-[15px] leading-7">
          Six months of books for a fictional small business, Bramblewood Joinery Ltd, with nothing to set up and no
          sign-in. Every document in it is labelled as fictional sample data. You get your own copy, kept in memory on
          our server and reset after 2 hours, so nothing you change reaches anyone else, and nothing about you is kept.
        </p>
        <div>
          <TryDemo next="/review" label="Start the demo" always />
        </div>
        <div className="rounded-2xl border border-border bg-white p-4">
          <h2 className="text-[15px] font-extrabold">Also: the personal demo</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Accnomos also keeps a household&apos;s own money. The personal demo opens a fictional family&apos;s bank lines
            sorted into budgets, their bills and subscriptions, and goals such as saving for school fees or spending less on
            coffee, each tracked against their books with suggestions.
          </p>
          <div className="mt-3">
            <TryDemo kind="personal" next="/" label="Start the personal demo" variant="secondary" always />
          </div>
        </div>
      </header>

      <section aria-labelledby="what-to-try" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="what-to-try" className="text-lg font-extrabold">
          What to try
        </h2>
        <p className="mt-1 text-sm text-muted">In this order if you like, or jump to whatever you do most.</p>
        <ol className="mt-3 flex flex-col gap-4">
          {steps.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span
                aria-hidden="true"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-teal-tint text-[14px] font-extrabold text-teal-dark"
              >
                {i + 1}
              </span>
              <div>
                <h3 className="text-[15px] font-extrabold">
                  <Link href={s.href} className="text-teal-dark underline underline-offset-2 hover:text-teal">
                    {s.title}
                  </Link>
                </h3>
                <p className="mt-0.5 text-[15px] leading-7 text-muted">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="what-is-real" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="what-is-real" className="text-lg font-extrabold">
          What is real in the demo, and what is not
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          <li>
            <strong>Real:</strong> the app, the checks, the ledger and VAT arithmetic, and the AI that reads your
            documents. Scanning anything still in <em>00 Inbox</em>, or a receipt you add, sends it to that AI.{" "}
            <Link href="/meta-models" className="font-bold text-teal-dark underline underline-offset-2">
              Which Meta model does what
            </Link>
            .
          </li>
          <li>
            <strong>Already read:</strong> the six documents waiting in Review were read when the sample books were made,
            so you can start without waiting for a model.
          </li>
          <li>
            <strong>HMRC sandbox:</strong> the VAT return goes to HMRC&apos;s own test service, with a test user made for
            your demo, HMRC&apos;s sign-in page, its periods and its receipt. No real tax is filed; filing for real needs
            HMRC&apos;s approval. If the sandbox can&apos;t be reached, the card says so and simulates the submission instead.
          </li>
          <li>
            <strong>Simulated:</strong> email is never sent (you&apos;ll see “Sent (demo — not actually sent)”), the bank
            feed is a test bank, and the Companies House and VAT-number look-ups are switched off.
          </li>
          <li>
            <strong>Not kept:</strong> anything about you. There is no account behind the demo, and its books are gone
            after 2 hours idle or when you press Reset demo.
          </li>
        </ul>
      </section>

      <section aria-labelledby="own-books" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="own-books" className="text-lg font-extrabold">
          Ready for your own books?
        </h2>
        <p className="mt-2 text-[15px] leading-7">
          Sign in with Microsoft and Accnomos sets up real books in a folder in your own OneDrive: it keeps no copy, and
          HMRC submissions go to HMRC&apos;s sandbox. You can load these same sample books there with one button, to try
          things on before your own paperwork arrives.{" "}
          <Link href="/connect" className="font-bold text-teal-dark underline underline-offset-2">
            Connect your OneDrive
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
