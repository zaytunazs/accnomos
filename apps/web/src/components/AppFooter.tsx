"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CONTACT_EMAIL } from "@/lib/public-site";
import { APP_VERSION } from "@/lib/version";

const linkClass = "hover:text-teal-dark hover:underline underline-offset-2";

/** The build's commit from the deploy's /version.json (StatusStrips' VersionStrip reads the same file), if any. */
function useBuild(): string | null {
  const [sha, setSha] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetch("/version.json", { cache: "no-store" })
      .then(async (res) => {
        const text = await res.text(); // drain the body either way (VersionStrip explains why)
        if (!res.ok) return;
        const info = JSON.parse(text) as { sha?: unknown };
        if (live && typeof info.sha === "string" && info.sha) setSha(info.sha.slice(0, 7));
      })
      .catch(() => undefined); // most builds have no version file: show the version alone
    return () => {
      live = false;
    };
  }, []);
  return sha;
}

/**
 * The footer on every app page (AppShell): how it works, help, privacy, the Meta models, judges, contact, Settings
 * (the last link on every page, where keyboard users leave it) and the version. The public site has its own footer (MarketingShell).
 */
export default function AppFooter() {
  const build = useBuild();
  return (
    <footer className="mx-auto mt-10 w-full max-w-3xl border-t border-border pb-2 pt-4 xl:max-w-5xl print:hidden">
      <nav aria-label="About" className="flex flex-wrap gap-x-5 gap-y-2 text-sm font-semibold text-muted">
        <Link href="/how-it-works" className={linkClass}>
          How it works
        </Link>
        <Link href="/help" className={linkClass}>
          Help and guides
        </Link>
        <Link href="/privacy" className={linkClass}>
          Privacy
        </Link>
        <Link href="/models" className={linkClass}>
          Meta models at work
        </Link>
        <Link href="/meta-models" className={linkClass}>
          Meta models used
        </Link>
        <Link href="/judges" className={linkClass}>
          For judges
        </Link>
        <a href={`mailto:${CONTACT_EMAIL}`} className={linkClass}>
          Contact
        </a>
        <Link href="/settings" className={linkClass}>
          Settings
        </Link>
      </nav>
      <p className="mt-2 text-xs text-muted">
        Accnomos version {APP_VERSION}
        {build ? ` · build ${build}` : ""} · your books stay in your OneDrive
      </p>
    </footer>
  );
}
