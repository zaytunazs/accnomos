import Link from "next/link";

const points = [
  {
    title: "Your data stays yours",
    body: "Books, receipts and VAT returns live in your own OneDrive. Accnomos runs no user database and keeps no copy — delete the folder and it is gone.",
  },
  {
    title: "AI you control",
    body: "Run Meta's open-weight Muse Glimmer on your own machine, or bring your own Meta API key. Either way the key or the address never leaves your device.",
  },
  {
    title: "You approve, code calculates",
    body: "AI proposes every entry; nothing is posted until you say so. The ledger and the 9-box VAT return are computed by deterministic code, not by a model.",
  },
];

/** Public pitch shown at the top of the home page: why Accnomos is different. */
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
          <p className="text-[15px] leading-relaxed text-muted">
            Snap a receipt, approve what the AI read, and your ledger, Books.xlsx and VAT return are written
            straight into <strong className="text-ink">your</strong> OneDrive. No cloud accounting platform holding
            your data. No subscription lock-in on your own numbers.
          </p>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/connect"
              className="whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Connect your OneDrive
            </Link>
            <Link
              href="/review"
              className="whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-ink hover:bg-ground"
            >
              See the demo books
            </Link>
            <Link
              href="/how-it-works"
              className="whitespace-nowrap rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-bold text-teal-dark hover:bg-ground"
            >
              How it works
            </Link>
          </div>
        </div>
        <div
          aria-hidden="true"
          className="min-h-[220px] bg-[#0A4F47] bg-cover bg-center"
          style={{ backgroundImage: "url(/brand/hero.jpg)" }}
        />
      </div>
      <ul className="grid gap-px border-t border-border bg-border min-[760px]:grid-cols-3">
        {points.map((p) => (
          <li key={p.title} className="bg-white p-5">
            <p className="text-sm font-extrabold text-ink">{p.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{p.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
