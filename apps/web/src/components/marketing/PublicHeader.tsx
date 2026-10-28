"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { openChat, SUBMISSION_MODE } from "@/lib/public-site";
import { LogoMark } from "./Marks";

const NAV: { href: string; label: string }[] = [
  { href: "/#features", label: "Features" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/privacy", label: "Security & privacy" },
  { href: "/#faq", label: "FAQ" },
];

/**
 * The public top menu (signed out only; SiteShell.tsx swaps in the app shell, with its own signed-in header, once
 * this device is signed in). From 1024 px every item is in the bar; below that a Menu button opens the same list.
 */
export default function PublicHeader({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const signIn = `/connect?next=${encodeURIComponent(path)}`;

  // Escape closes the menu and gives focus back to its button; so does a wide window.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    const wide = window.matchMedia("(min-width: 1024px)");
    const onWide = () => wide.matches && setOpen(false);
    document.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => {
      document.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  const current = (href: string) => (href === path ? "page" : undefined);
  const ask = () => {
    setOpen(false);
    openChat();
  };

  return (
    <header className="on-dark sticky top-0 z-40 border-b border-white/10 bg-ledger text-ground">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2.5 rounded-lg" aria-label="Accnomos home">
          <LogoMark className="bg-ground" stroke="#0A4F47" />
          <span className="text-lg font-extrabold tracking-tight">Accnomos</span>
        </Link>

        <nav aria-label="Site" className="ml-6 hidden lg:block">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={current(item.href)}
                  className="rounded-lg px-3 py-2 text-[15px] font-semibold text-ground/85 hover:bg-white/10 hover:text-ground aria-[current=page]:text-brass"
                >
                  {item.label}
                </Link>
              </li>
            ))}
            <li>
              <button
                type="button"
                onClick={ask}
                className="rounded-lg px-3 py-2 text-[15px] font-semibold text-ground/85 hover:bg-white/10 hover:text-ground"
              >
                Ask about Accnomos
              </button>
            </li>
            {!SUBMISSION_MODE && (
              <li>
                <Link href={signIn} className="rounded-lg px-3 py-2 text-sm font-semibold text-ground/65 hover:text-ground">
                  Early access / testers
                </Link>
              </li>
            )}
          </ul>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {SUBMISSION_MODE && (
            <Link
              href={signIn}
              className="whitespace-nowrap rounded-lg px-3 py-2 text-[15px] font-bold text-ground hover:bg-white/10"
            >
              Sign in
            </Link>
          )}
          <Link
            href="/try"
            className="hidden whitespace-nowrap rounded-lg bg-brass px-4 py-2 text-[15px] font-bold text-ink hover:bg-brass-light sm:inline-block"
          >
            Try the sample books
          </Link>
          <button
            ref={button}
            type="button"
            aria-expanded={open}
            aria-controls="site-menu"
            onClick={() => setOpen((o) => !o)}
            className="flex h-11 items-center gap-2 rounded-lg border border-white/20 px-3 text-[15px] font-bold lg:hidden"
          >
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18" fill="none">
              {open ? (
                <path d="M4 4l10 10M14 4L4 14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              ) : (
                <path d="M2.5 5h13M2.5 9h13M2.5 13h13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              )}
            </svg>
            Menu
          </button>
        </div>
      </div>

      <div
        id="site-menu"
        ref={panel}
        hidden={!open}
        className="border-t border-white/10 bg-ledger px-4 pb-5 pt-2 lg:hidden"
      >
        <nav aria-label="Site menu">
          <ul className="flex flex-col">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={current(item.href)}
                  onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-3 text-base font-semibold hover:bg-white/10 aria-[current=page]:text-brass"
                >
                  {item.label}
                </Link>
              </li>
            ))}
            <li>
              <button
                type="button"
                onClick={ask}
                className="block w-full rounded-lg px-3 py-3 text-left text-base font-semibold hover:bg-white/10"
              >
                Ask about Accnomos
              </button>
            </li>
            {!SUBMISSION_MODE && (
              <li>
                <Link
                  href={signIn}
                  onClick={() => setOpen(false)}
                  className="block rounded-lg px-3 py-3 text-sm font-semibold text-ground/70 hover:bg-white/10"
                >
                  Early access / testers
                </Link>
              </li>
            )}
          </ul>
        </nav>
        <Link
          href="/try"
          onClick={() => setOpen(false)}
          className="mt-3 block rounded-lg bg-brass px-4 py-3 text-center text-base font-bold text-ink hover:bg-brass-light"
        >
          Try the sample books
        </Link>
      </div>
    </header>
  );
}
