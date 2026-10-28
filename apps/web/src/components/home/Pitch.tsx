import Link from "next/link";
import TryDemo from "@/components/demo/TryDemo";

const claims = [
  {
    title: "Your books live in your OneDrive",
    body: "Receipts, ledger, Books.xlsx and VAT returns sit in your own OneDrive folder. Accnomos runs no user database and keeps no copy.",
  },
  {
    title: "AI proposes, you approve, code calculates",
    body: "The AI reads each receipt and proposes an entry; nothing is posted until you approve it. The ledger and the 9-box VAT return are worked out by deterministic code, never by a model.",
  },
  {
    title: "AI you control",
    body: "Run Meta's open-weight Muse Glimmer on your own machine, or bring your own Meta API key. The address or the key never leaves your device.",
  },
];

/** Public pitch above the sample books: the three claims that are true today, with Connect as the one action. */
export default function Pitch() {
  return (
    <section
      aria-labelledby="pitch"
      className="overflow-hidden rounded-2xl border border-border bg-white"
    >
      <div className="grid gap-0 min-[760px]:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-4 p-6 sm:p-8">
          <p className="text-xs font-extrabold uppercase tracking-[0.08em] text-teal-dark">
            Bookkeeping for UK small businesses
          </p>
          <h2 id="pitch" className="text-3xl font-extrabold leading-[1.1] tracking-tight sm:text-4xl">
            Books read by AI.
            <br />
            Approved by you.
            <br />
            <span className="text-teal">Stored only by you.</span>
          </h2>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Link
              href="/connect?next=%2Ftry"
              className="whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Connect your OneDrive
            </Link>
            <TryDemo variant="secondary" />
            <Link
              href="/review"
              className="text-sm font-bold text-teal-dark underline underline-offset-2 hover:text-teal"
            >
              See the demo books
            </Link>
            <Link
              href="/how-it-works"
              className="text-sm font-bold text-teal-dark underline underline-offset-2 hover:text-teal"
            >
              How it works
            </Link>
          </div>
        </div>
        {/* Phones get an 800 px copy (47 kB, not 164 kB); only the matching background is ever fetched (docs/PERF.md). */}
        <div
          aria-hidden="true"
          className="min-h-[220px] bg-[#0A4F47] bg-[url(/brand/hero-800.jpg)] bg-cover bg-center min-[481px]:bg-[url(/brand/hero.jpg)]"
        />
      </div>
      <ul className="grid gap-px border-t border-border bg-border min-[760px]:grid-cols-3">
        {claims.map((p) => (
          <li key={p.title} className="bg-white p-5">
            <p className="text-sm font-extrabold text-ink">{p.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{p.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
