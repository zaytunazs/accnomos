"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import AiSidebarLabel from "./AiSidebarLabel";
import ClientBanner from "./accountant/ClientBanner";
import AppFooter from "./AppFooter";
import AppNav from "./AppNav";
import BankFeedOnOpen from "./bank/BankFeedOnOpen";
import DemoBanner from "./DemoBanner";
import MonthlyBackup from "./files/MonthlyBackup";
import DemoBar, { DemoMenu, NotInDemo } from "./demo/DemoBar";
import { AccountMenu, useLinkedProfiles } from "./ProfileMenu";
import TopBar, { LogoMark } from "./TopBar";
import { ServiceStrip, VersionStrip } from "./StatusStrips";
import { ScanStatus } from "./review/ScanProgress";
import { getClientContext, onClientContextChange } from "@/lib/accountant";
import { useSignedIn } from "@/lib/signed-in";

/** /accountant, while no client's books are open in this tab: the accountant portal's own shell. */
function useAccountantShell(path: string): boolean {
  const [client, setClient] = useState(false);
  useEffect(() => {
    queueMicrotask(() => setClient(getClientContext() !== null));
    return onClientContextChange(() => setClient(getClientContext() !== null));
  }, []);
  return (path === "/accountant" || path.startsWith("/accountant/")) && !client;
}

/**
 * The accountant portal's minimal bar: the logo, "Accountant portal", and the accountant's name, email and sign out.
 * No business menu: an accountant here is looking at their clients, not at books of their own.
 */
function AccountantBar() {
  const linked = useLinkedProfiles();
  return (
    <header data-accountant-bar="" className="sticky top-0 z-40 border-b border-border bg-white print:hidden">
      <div className="flex min-h-14 items-center gap-2 px-2 sm:px-4">
        <Link href="/accountant" className="flex h-11 min-w-0 items-center gap-2 rounded-xl px-1.5 hover:bg-ground">
          <LogoMark />
          <span className="truncate text-lg font-extrabold tracking-tight">
            Accnomos <span className="font-semibold text-muted">· Accountant portal</span>
          </span>
        </Link>
        <div className="ml-auto flex shrink-0 items-center">
          {linked ? (
            <AccountMenu linked={linked} minimal />
          ) : linked === null ? (
            <Link
              href="/connect?next=%2Faccountant"
              className="flex min-h-11 items-center whitespace-nowrap rounded-xl bg-teal px-3 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Sign in with Microsoft
            </Link>
          ) : null}
        </div>
      </div>
    </header>
  );
}

/**
 * The app's frame. Signed in: the menu bar (TopBar) on every page, the page, the footer (AppFooter) and, on phones,
 * the five-tab bar; there is no sidebar, so the links are never listed twice. Signed out (the sample books on the
 * app routes): the sidebar with the sample's sections, the phone header and the same footer. The accountant portal
 * (/accountant with no client open) has its own minimal bar. `routes`: the pages in this build
 * (lib/routes.server.ts, read by the root layout), for the menu bar.
 */
export default function AppShell({ children, routes }: { children: ReactNode; routes: string[] }) {
  const path = usePathname() ?? "/";
  const signedIn = useSignedIn(path);
  const accountant = useAccountantShell(path);
  // Before the client check, the probe in layout.tsx has already marked <html data-signed-in>: globals.css hides
  // the signed-out chrome ([data-signed-out-chrome]) for a signed-in device, so nothing flashes.
  const signedOutChrome = signedIn !== true && !accountant;

  // The footer sits after <main>, not in it, so it is the page's contentinfo landmark.
  const main = (
    <div className="flex min-w-0 flex-1 flex-col px-4 pb-28 pt-6 sm:px-8 min-[900px]:py-8 min-[900px]:pb-8">
      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-3xl xl:max-w-5xl">{children}</div>
      </main>
      <AppFooter />
    </div>
  );

  return (
    <div className="group/shell flex min-h-full flex-1 flex-col">
      <DemoBar />
      <DemoBanner />
      <ClientBanner />
      <MonthlyBackup />
      <BankFeedOnOpen />
      {/* Reader trouble and new-version notices: one shared strip each, pages keep what they can below. */}
      <ServiceStrip />
      {/* A scan started on Review keeps going on every other page; this says how far it got. */}
      <ScanStatus />
      <VersionStrip />
      {accountant ? <AccountantBar /> : signedIn ? <TopBar routes={routes} /> : null}
      {signedOutChrome && (
        // Signed out, on phones: the logo plus Settings (the sidebar is hidden under 900 px).
        <header
          data-signed-out-chrome=""
          className="sticky top-0 z-40 flex items-center justify-between gap-3 border-b border-border bg-white px-4 py-2.5 min-[900px]:hidden"
        >
          <span className="flex min-w-0 items-center gap-2.5">
            <LogoMark />
            <span className="truncate text-lg font-extrabold tracking-tight">Accnomos</span>
          </span>
          <Link
            href="/settings"
            className="shrink-0 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-bold text-teal-dark hover:bg-ground"
          >
            Settings
          </Link>
        </header>
      )}
      {/* One wrapper whatever the sign-in state: swapping it would remount the page (and lose, say, the HMRC code
          the VAT page has just read from the address) when the sign-in check answers after the first render. */}
      <div className="flex flex-1 flex-col min-[900px]:flex-row">
        {signedOutChrome && (
          <aside
            data-signed-out-chrome=""
            className="hidden w-full shrink-0 flex-col gap-6 border-b border-border bg-white p-5 min-[900px]:flex min-[900px]:w-[232px] min-[900px]:border-b-0 min-[900px]:border-r"
          >
            <div className="flex items-center gap-2.5">
              <LogoMark />
              <span className="text-lg font-extrabold tracking-tight">Accnomos</span>
            </div>
            <AppNav variant="sidebar" />
            <div className="mt-auto flex flex-col gap-3">
              <DemoMenu />
              <NotInDemo>
                <p className="rounded-2xl bg-ground p-4 text-sm leading-6 text-muted">
                  Your books live in OneDrive — Apps / Accnomos
                </p>
              </NotInDemo>
              <AiSidebarLabel />
            </div>
          </aside>
        )}
        {main}
      </div>
      {/* Phone tab bar (Home, Review, Ask, VAT, Files) lives in AppNav; not in the accountant portal. */}
      {!accountant && <AppNav variant="tabs" />}
    </div>
  );
}
