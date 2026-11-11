import Link from "next/link";
import TryDemo from "@/components/demo/TryDemo";
import { DEMO_GUIDE, HONESTY_URL } from "@/lib/public-site";

export const metadata = { title: "For judges · Accnomos", robots: { index: false, follow: false } };

const REPO = "https://github.com/zaytunazs/accnomos";
const link = "font-bold text-teal-dark underline underline-offset-2 hover:text-teal";

/**
 * The hackathon judges' notes: how to start the demo, what is real and what is simulated, and where the evidence is
 * in the repository. Linked from the footers and the README only; the tour of the sample books that "Try the demo"
 * opens is the customer-facing /demo page.
 */
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
        <div className="flex flex-wrap items-center gap-3">
          <TryDemo next="/review" label="Start the demo" always />
          <TryDemo kind="personal" next="/" label="Start the personal demo" variant="secondary" always />
        </div>
        <p className="text-[15px] leading-7">
          Start the demo opens Review, with six documents waiting. What to try from there, in order (review and approve a
          receipt, ask by voice or text, invoices, bank matching, a VAT return to HMRC&apos;s sandbox, goals, and the personal
          demo of a household&apos;s own money), is{" "}
          <Link href={DEMO_GUIDE} className={link}>
            the demo guide
          </Link>
          , the page &ldquo;Try the demo&rdquo; opens for everyone.
        </p>
      </header>

      <section aria-labelledby="what-is-real" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="what-is-real" className="text-lg font-extrabold">
          What is real here, and what is simulated
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          <li>
            <strong>Real:</strong> the app, the checks, the ledger and VAT arithmetic, and the AI (the model this server is
            set up with). Scanning the documents still in <em>00 Inbox</em> sends them to that AI.{" "}
            <Link href="/ai-models" className={link}>
              Which AI model does what
            </Link>
            .
          </li>
          <li>
            <strong>Pre-read:</strong> the six documents waiting in Review were read when the sample books were made, from the
            fields printed on them, so you can start without waiting for a model.
          </li>
          <li>
            <strong>HMRC sandbox:</strong> the VAT return goes to HMRC&apos;s sandbox, HMRC&apos;s own test service: a test user
            made for your demo, HMRC&apos;s sign-in page, HMRC&apos;s periods and receipt. No real tax is filed; live filing needs
            HMRC&apos;s approval. If the sandbox can&apos;t be reached, the card says so and simulates the submission instead.
          </li>
          <li>
            <strong>Simulated:</strong> email is never sent (you&apos;ll see “Sent (demo — not actually sent)”), the bank feed
            connects a test bank, and the Companies House and VAT-number look-ups are switched off.
          </li>
          <li>
            <strong>Not stored:</strong> nothing about you. There is no Microsoft account behind the demo, and its books are
            gone after 2 hours idle or when you press Reset demo.
          </li>
        </ul>
      </section>

      <section aria-labelledby="how-to-run" className="rounded-2xl border border-border bg-white p-5 sm:p-6">
        <h2 id="how-to-run" className="text-lg font-extrabold">
          How to run it, and where the evidence is
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-7">
          <li>
            <strong>What it does and how to try it</strong>, including how to run the whole thing in test mode with no
            accounts:{" "}
            <a href={`${REPO}#try-it`} className={link}>
              README › Try it
            </a>
            .
          </li>
          <li>
            <strong>AI models</strong>, where each runs and what is measured against what is unit-tested:{" "}
            <a href={`${REPO}/blob/main/docs/AI_MODELS.md`} className={link}>
              docs/AI_MODELS.md
            </a>
            . Every accuracy figure is on synthetic documents.
          </li>
          <li>
            <strong>What pre-existed</strong> and how each part was built, with timestamps:{" "}
            <a href={`${REPO}/blob/main/docs/PROVENANCE.md`} className={link}>
              docs/PROVENANCE.md
            </a>
            .
          </li>
          <li>
            <strong>What is not tested against real services</strong> (HMRC is sandbox only; most features are tested on
            fakes):{" "}
            <a href={HONESTY_URL} className={link}>
              docs/HONESTY.md
            </a>
            .
          </li>
          <li>
            <strong>Android:</strong> the APK on the repository&apos;s{" "}
            <a href={`${REPO}/releases`} className={link}>
              Releases page
            </a>{" "}
            opens the same demo with Try the demo.
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
          <Link href="/connect" className={link}>
            Connect your OneDrive
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
