import type { ReactNode } from "react";
import Link from "next/link";
import AiSidebarLabel from "./AiSidebarLabel";
import AppNav from "./AppNav";
import BankFeedOnOpen from "./bank/BankFeedOnOpen";
import DemoBanner from "./DemoBanner";
import MonthlyBackup from "./files/MonthlyBackup";
import { ServiceStrip, VersionStrip } from "./StatusStrips";

function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal"
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path
          d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6L10 2.5Z"
          stroke="#F4F3EE"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="M7 10.2l2.1 2.1L13.2 8"
          stroke="#F4F3EE"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <DemoBanner />
      <MonthlyBackup />
      <BankFeedOnOpen />
      {/* Reader trouble and new-version notices: one shared strip each, pages keep what they can below. */}
      <ServiceStrip />
      <VersionStrip />
      {/* Phone header: logo plus Settings, shown only while the sidebar is hidden. */}
      <header className="sticky top-0 z-40 flex items-center justify-between gap-3 border-b border-border bg-white px-4 py-2.5 min-[900px]:hidden">
        <span className="flex min-w-0 items-center gap-2.5">
          <LogoMark />
          <span className="truncate text-lg font-extrabold tracking-tight">
            Accnomos
          </span>
        </span>
        <Link
          href="/settings"
          className="shrink-0 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-bold text-teal-dark hover:bg-ground"
        >
          Settings
        </Link>
      </header>
      <div className="flex flex-1 flex-col min-[900px]:flex-row">
        <aside className="hidden w-full shrink-0 flex-col gap-6 border-b border-border bg-white p-5 min-[900px]:flex min-[900px]:w-[232px] min-[900px]:border-b-0 min-[900px]:border-r">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <span className="text-lg font-extrabold tracking-tight">
              Accnomos
            </span>
          </div>
          <AppNav variant="sidebar" />
          <div className="mt-auto flex flex-col gap-3">
            <p className="rounded-2xl bg-ground p-4 text-sm leading-6 text-muted">
              Your books live in OneDrive — Apps / Accnomos
            </p>
            <AiSidebarLabel />
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-4 pb-28 pt-6 sm:px-8 min-[900px]:py-8 min-[900px]:pb-8">
          <div className="mx-auto w-full max-w-3xl">{children}</div>
          <footer className="mx-auto mt-10 w-full max-w-3xl border-t border-border pt-4 pb-2">
            <nav aria-label="About" className="flex flex-wrap gap-x-5 gap-y-2 text-sm font-semibold text-muted">
              <Link href="/how-it-works" className="hover:text-teal-dark hover:underline underline-offset-2">
                How it works
              </Link>
              <Link href="/privacy" className="hover:text-teal-dark hover:underline underline-offset-2">
                Privacy
              </Link>
              <Link href="/settings" className="hover:text-teal-dark hover:underline underline-offset-2">
                Settings
              </Link>
            </nav>
          </footer>
        </main>
      </div>
      {/* Phone tab bar (Home, Review, Ask, VAT, Files) lives in AppNav. */}
      <AppNav variant="tabs" />
    </div>
  );
}
