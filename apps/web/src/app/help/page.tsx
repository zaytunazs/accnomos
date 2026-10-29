import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import { CONTACT_EMAIL, HONESTY_URL } from "@/lib/public-site";

export const metadata = { title: "Help and guides · Accnomos" };

const GUIDES: { href: string; title: string; body: string }[] = [
  { href: "/how-it-works", title: "How it works", body: "From a receipt in your Inbox to an approved entry in your own OneDrive, step by step." },
  { href: "/review", title: "Review and approve", body: "Every reading is a card: check it, change it if needed, approve it. Nothing is posted without you." },
  { href: "/files", title: "Files and backups", body: "Where your documents are, earlier files not read yet, Back up now and how to restore." },
  { href: "/vat", title: "VAT returns", body: "The nine boxes worked out from your approved entries, and the file ready for HMRC." },
  { href: "/ask", title: "Ask about your books", body: "Questions in plain words; the figures come from your ledger, not from the AI." },
  { href: "/meta-models", title: "Meta models at work", body: "Which Meta Muse models read your documents and how they scored on our test sets." },
  { href: "/settings", title: "Settings", body: "Your business, VAT periods, AI choice, your accountant, files and backups, your data." },
  { href: "/judges", title: "For judges", body: "The demo sandbox and the guided tour of the sample books." },
];

/** Help and guides: one page that points at the guide for each part of the app (footer link). */
export default function HelpPage() {
  return (
    <div className="flex flex-col">
      <PageHeader title="Help and guides" description="Short guides to each part of Accnomos, and how to reach us." />
      <ul aria-label="Guides" className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
        {GUIDES.map((g) => (
          <li key={g.href}>
            <Link href={g.href} className="block h-full rounded-2xl border border-border bg-white p-4 hover:bg-ground">
              <span className="block text-[15px] font-extrabold text-teal-dark">{g.title}</span>
              <span className="mt-1 block text-sm text-ink">{g.body}</span>
            </Link>
          </li>
        ))}
      </ul>
      <section aria-labelledby="help-contact" className="mt-6 rounded-2xl border border-border bg-white p-4">
        <h2 id="help-contact" className="text-[15px] font-extrabold">
          Still stuck?
        </h2>
        <p className="mt-1 text-sm text-ink">
          Email{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className="font-bold text-teal-dark underline underline-offset-2">
            {CONTACT_EMAIL}
          </a>
          . What is and is not tested against real services is listed in{" "}
          <a href={HONESTY_URL} className="font-bold text-teal-dark underline underline-offset-2">
            HONESTY.md
          </a>
          .
        </p>
      </section>
    </div>
  );
}
