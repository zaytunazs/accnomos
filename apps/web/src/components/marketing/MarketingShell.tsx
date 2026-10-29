"use client";

import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { VersionStrip } from "@/components/StatusStrips";
import { CONTACT_EMAIL, DEMO_GUIDE, HONESTY_URL } from "@/lib/public-site";
import { LogoMark } from "./Marks";
import PublicHeader from "./PublicHeader";

// The chat's panel and logic load after the page: only its launcher button is in the first paint.
const ChatWidget = dynamic(() => import("./ChatWidget"), { ssr: false });

/**
 * The public website's frame (SiteShell.tsx): top menu, the page, footer and the "Ask about Accnomos" chat.
 * `/` is full-bleed (the landing page lays out its own bands); the other public pages sit in a reading column.
 */
export default function MarketingShell({ path, children }: { path: string; children: ReactNode }) {
  return (
    <div data-public-only className="flex min-h-full flex-1 flex-col bg-ground">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-brass px-4 py-2 font-bold text-ink focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <VersionStrip />
      <PublicHeader path={path} />
      <main id="main" className="flex-1">
        {path === "/" ? children : <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8">{children}</div>}
      </main>
      <SiteFooter />
      <ChatWidget />
    </div>
  );
}

function SiteFooter() {
  return (
    <footer className="on-dark bg-ledger-deep text-ground/80">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5 text-ground">
            <LogoMark className="bg-ground" stroke="#0A4F47" />
            <span className="text-lg font-extrabold tracking-tight">Accnomos</span>
          </div>
          {/* Footer microcopy from docs/marketing/COPY.md. */}
          <p className="mt-3 max-w-sm text-sm leading-relaxed">
            Accounting, intelligently done. Your books stay in your OneDrive. Sample figures on this page are fictional.
            HMRC contact is sandbox only.
          </p>
          <p className="mt-3 max-w-sm text-sm leading-relaxed">
            Built for the Meta Global AI Developer Hackathon by Zaytuna Business Services Ltd.
          </p>
          <p className="mt-3 text-sm">
            Questions:{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="font-bold text-ground underline underline-offset-2">
              {CONTACT_EMAIL}
            </a>
          </p>
        </div>
        <FooterLinks
          label="Product"
          links={[
            { href: "/#features", text: "Features" },
            { href: "/#how", text: "How it works" },
            { href: "/#accountants", text: "For accountants" },
            { href: "/#pricing", text: "Pricing" },
            { href: DEMO_GUIDE, text: "Try the demo" },
            { href: "/try", text: "Browse the sample books" },
            { href: "/join", text: "Get 3 months free" },
          ]}
        />
        <FooterLinks
          label="Trust"
          links={[
            { href: "/privacy", text: "Privacy policy" },
            { href: "/terms", text: "Terms of use" },
            { href: "/#status", text: "What is tested" },
            { href: HONESTY_URL, text: "What is not tested (HONESTY.md)" },
          ]}
        />
        <FooterLinks
          label="Help"
          links={[
            { href: "/#faq", text: "FAQ" },
            { href: "/how-it-works", text: "How each feature works" },
            { href: `mailto:${CONTACT_EMAIL}`, text: "Contact us" },
          ]}
        />
      </div>
    </footer>
  );
}

function FooterLinks({ label, links }: { label: string; links: { href: string; text: string }[] }) {
  const cls = "hover:text-ground hover:underline";
  return (
    <nav aria-label={label}>
      <p className="text-sm font-bold text-ground">{label}</p>
      <ul className="mt-3 space-y-2 text-sm">
        {links.map((l) => (
          <li key={l.href}>
            {l.href.startsWith("/") ? (
              <Link href={l.href} className={cls}>
                {l.text}
              </Link>
            ) : (
              <a href={l.href} className={cls}>
                {l.text}
              </a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
