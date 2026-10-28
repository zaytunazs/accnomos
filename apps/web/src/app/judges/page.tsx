import Link from "next/link";
import TryDemo from "@/components/demo/TryDemo";

export const metadata = { title: "For judges · Accnomos" };

const steps: { title: string; href: string; body: string }[] = [
  {
    title: "Review a receipt",
    href: "/review",
    body: "Six documents are waiting. Open one: what the AI read, the checks code ran on it, and the journal it would post. Two need a look (an invoice in euros and a malformed VAT number).",
  },
  {
    title: "Approve",
    href: "/review",
    body: "Approve a receipt: nothing is posted until you do. The entry lands in the ledger and Books.xlsx, and can be undone with a reversing entry.",
  },
  {
    title: "VAT return",
    href: "/vat",
    body: "The 9 boxes, worked out by code from approved entries, with the entries behind each box. Connect to HMRC and submit to see the whole flow; in the demo it ends on a receipt labelled “Demo — submission simulated”.",
  },
  {
    title: "Ask",
    href: "/ask",
    body: "Ask “How much VAT do I owe this quarter?” or “Send a £100 invoice to Hartwell Property Maintenance”. The figures come from code; the AI only explains them, and an action waits for your Approve.",
  },
  {
    title: "Reports",
    href: "/reports",
    body: "Profit and loss, aged debtors and creditors, the VAT summary and the trend, over six months of books.",
  },
  {
    title: "Contacts",
    href: "/contacts",
    body: "Customers and suppliers built from the ledger: who owes what, which suppliers aren't VAT-registered, and Import from Outlook (a demo address book).",
  },
  {
    title: "Bank",
    href: "/bank",
    body: "Two imported statements reconciled against the books, bank rules coding the regular lines, and what is still to match.",
  },
];

export default function JudgesPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <p className="text-xs font-extrabold uppercase tracking-[0.08em] text-teal-dark">For judges</p>
        <h1 className="text-3xl font-extrabold leading-tight tracking-tight">Try Accnomos in one click</h1>
        <p className="text-[15px] leading-7">
          This sandbox is specially for testing. It opens six months of books for a fictional company, Bramblewood Joinery
          Ltd (every document in it is labelled as fictional sample data), with no Microsoft sign-in and no
          two-step verification. Each visitor gets their own copy, kept in memory on our server and reset after 2 hours, so
          nothing you change reaches anyone else.
        </p>
        <div>
          <TryDemo next="/review" label="Start the demo" always />
        </div>
      </header>

      <section aria-labelledby="what-to-try" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="what-to-try" className="text-lg font-extrabold">
          What to try, in this order
        </h2>
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
          What is real here, and what is simulated
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          <li>
            <strong>Real:</strong> the app, the checks, the ledger and VAT arithmetic, and the AI (the model this server is
            set up with). Scanning the documents still in <em>00 Inbox</em> sends them to that AI.
          </li>
          <li>
            <strong>Pre-read:</strong> the six documents waiting in Review were read when the sample books were made, from the
            fields printed on them, so you can start without waiting for a model.
          </li>
          <li>
            <strong>Simulated:</strong> email is never sent (you&apos;ll see “Sent (demo — not actually sent)”), HMRC is never
            contacted, and the Companies House and VAT-number look-ups are switched off.
          </li>
          <li>
            <strong>Not stored:</strong> nothing about you. There is no Microsoft account behind the demo, and its books are
            gone after 2 hours idle or when you press Reset demo.
          </li>
        </ul>
      </section>

      <section aria-labelledby="own-books" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="own-books" className="text-lg font-extrabold">
          Your own books instead
        </h2>
        <p className="mt-2 text-[15px] leading-7">
          Signing in with Microsoft sets up real books in a folder in your own OneDrive: Accnomos keeps no copy, and HMRC
          submissions go to HMRC&apos;s sandbox. You can still load the same sample books there with one button.{" "}
          <Link href="/connect" className="font-bold text-teal-dark underline underline-offset-2">
            Connect your OneDrive
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
