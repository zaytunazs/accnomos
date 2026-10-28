import Link from "next/link";
import { CONTACT_EMAIL, HONESTY_URL } from "@/lib/public-site";

export const metadata = {
  title: "Terms of use — Accnomos",
  description: "The plain terms for using the Accnomos hackathon build, its demo and its sample books.",
};

const UPDATED = "28 October 2026";

/*
 * Plain-English terms for the hackathon build, written from README.md, docs/HONESTY.md and the privacy policy.
 * Not reviewed by a lawyer (docs/reviews/site-layout/REVIEW.md): the operator should have them checked before
 * real customers rely on the service.
 */
export default function TermsPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 text-ink">
      <h1 className="text-3xl font-extrabold tracking-tight">Terms of use</h1>
      <p className="mt-2 text-sm text-muted">Accnomos · Zaytuna Business Services Ltd · last updated {UPDATED}</p>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What Accnomos is</h2>
        <p>
          Accnomos is bookkeeping software built for the Meta Global AI Developer Hackathon by Zaytuna Business Services
          Ltd (UK). It is a hackathon build, not a finished commercial product, and it is offered without charge. What has
          and has not been tested against real services is listed in{" "}
          <a className="font-semibold text-teal-dark underline" href={HONESTY_URL}>
            docs/HONESTY.md
          </a>
          .
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">You approve, you stay responsible</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            The AI proposes entries; nothing reaches your books until you approve it. Check each proposal: a model can
            misread a document.
          </li>
          <li>
            Accnomos is not tax, legal or accounting advice. You remain responsible for your records and for what you
            send to HMRC. If you are unsure, ask an accountant.
          </li>
          <li>
            Direct submission to HMRC goes to HMRC&apos;s sandbox (its test service). For a real return, Accnomos prepares
            the figures and files for you to submit.
          </li>
        </ul>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Your books and your data</h2>
        <p>
          Your books are files in your own Microsoft OneDrive. We run no user database and keep no copy; you can export or
          delete them at any time. How we handle everything else is in the{" "}
          <Link className="font-semibold text-teal-dark underline" href="/privacy">
            privacy policy
          </Link>
          .
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">The demo and the sample books</h2>
        <p>
          The demo sandbox and the sample books use a fictional company. Each demo is kept in memory on our server, reset
          after 2 hours, and seen only by you. Please do not upload real documents to it.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Fair use and availability</h2>
        <p>
          Do not try to break, overload or misuse the service or other people&apos;s data. The service is provided as it is,
          may change or stop, and has not been load-tested; keep your own copy of anything important (your OneDrive
          already holds it).
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Contact</h2>
        <p>
          Questions about these terms:{" "}
          <a className="font-semibold text-teal-dark underline" href={`mailto:${CONTACT_EMAIL}`}>
            {CONTACT_EMAIL}
          </a>
          .
        </p>
      </section>
    </div>
  );
}
