import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import ReportProblemButton from "@/components/billing/ReportProblemButton";
import HelpSearch from "@/components/support/HelpSearch";
import { HELP_ARTICLES } from "@/lib/help";
import { CONTACT_EMAIL } from "@/lib/public-site";

export const metadata = {
  title: "Help centre · Accnomos",
  description: "Step-by-step guides for Accnomos on the web and Android: receipts, bank feeds, invoices and PayPal, VAT returns to HMRC, month-end and the assistant.",
  alternates: { canonical: "/help" },
};

const SITE = "https://accnomos.com";

const MORE: { href: string; title: string; body: string }[] = [
  { href: "/how-it-works", title: "How it works", body: "What the AI does, what code checks, and guides for payroll, goals, the calendar, contacts and more." },
  { href: "/demo", title: "Demo guide", body: "A tour of the fictional sample books, with nothing to sign in to." },
];

/** The help centre: every article (src/content/help/articles.json) by category, with search, and how to reach us. */
export default function HelpPage() {
  const ld = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "Accnomos help centre",
    url: `${SITE}/help`,
    hasPart: HELP_ARTICLES.map((a) => ({ "@type": "HowTo", name: a.title, url: `${SITE}/help/${a.id}` })),
  };
  return (
    <div className="flex flex-col">
      <PageHeader title="Help centre" description="Step-by-step guides for the web and the Android app, and how to reach us when a guide doesn't help." />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />
      <HelpSearch />
      <section aria-labelledby="help-more" className="mt-8 rounded-2xl border border-border bg-white p-4">
        <h2 id="help-more" className="text-[15px] font-extrabold">
          More guides
        </h2>
        <ul aria-label="Guides" className="mt-2 grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
          {MORE.map((g) => (
            <li key={g.href}>
              <Link href={g.href} className="block rounded-xl border border-border p-3 hover:bg-ground">
                <span className="block font-extrabold text-teal-dark">{g.title}</span>
                <span className="mt-0.5 block text-ink">{g.body}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="help-contact" className="mt-4 rounded-2xl border border-border bg-white p-4">
        <h2 id="help-contact" className="text-[15px] font-extrabold">
          Still stuck?
        </h2>
        <p className="mt-1 text-sm text-ink">
          Signed in, open{" "}
          <Link href="/support" className="font-bold text-teal-dark underline underline-offset-2">
            Support
          </Link>{" "}
          to ask the support assistant or raise a ticket. Or email{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className="font-bold text-teal-dark underline underline-offset-2">
            {CONTACT_EMAIL}
          </a>
          .
        </p>
        <ReportProblemButton />
      </section>
    </div>
  );
}
