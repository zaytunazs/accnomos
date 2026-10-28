"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import { useAccount } from "@/components/jobs/useAccount";
import { runtime } from "@/lib/runtime";

type NavLink = { href: string; label: string; badge?: string; tab?: string };
const links: NavLink[] = [
  { href: "/", label: "Home", tab: "Home" },
  { href: "/review", label: "Review", tab: "Review" },
  { href: "/ask", label: "Ask", tab: "Ask" },
  { href: "/invoices", label: "Invoices" },
  { href: "/bank", label: "Bank" },
  { href: "/vat", label: "VAT return", tab: "VAT" },
  { href: "/jobs", label: "Jobs" },
  { href: "/payroll", label: "Payroll" },
  { href: "/reports", label: "Reports" },
  { href: "/spending", label: "Spending" },
  { href: "/prices", label: "Cheaper options" },
  { href: "/shopping", label: "Shopping list" },
  { href: "/contacts", label: "Contacts" },
  { href: "/vehicles", label: "Vehicles" },
  { href: "/files", label: "Files", tab: "Files" },
];

const SAMPLE_WAITING = 1; // signed out, Review shows the one sample proposal

// One count per page shown, shared by the sidebar and the tab bar (both are mounted).
let waiting: { path: string; count: Promise<number | null> } | null = null;

function countWaiting(account: AccountInfo, path: string): Promise<number | null> {
  if (waiting?.path !== path) {
    const count = runtime.proposals(account).then(
      (all) => all.filter((p) => p.status === "proposed" || p.status === "needs_a_look").length,
      () => null, // no badge rather than a wrong one
    );
    waiting = { path, count };
  }
  return waiting.count;
}

/** The Review badge: proposals waiting for the user (refreshed on every page change), or the sample's one. */
function useReviewBadge(pathname: string): string | undefined {
  const account = useAccount();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    if (account === undefined) return;
    let stale = false;
    const count = account ? countWaiting(account, pathname) : Promise.resolve(SAMPLE_WAITING);
    count.then((n) => !stale && setCount(n));
    return () => {
      stale = true;
    };
  }, [account, pathname]);
  return count ? String(count) : undefined;
}

function withBadges(review: string | undefined): NavLink[] {
  return links.map((l) => (l.href === "/review" ? { ...l, badge: review } : l));
}

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The Review count. The link is named by its content ("Review 1 item to review"), never an aria-label, so the
 * visible "Review 1" is always part of the name (WCAG 2.5.3, axe label-content-name-mismatch).
 */
function Badge({ count, className }: { count: string; className: string }) {
  return (
    <>
      {" "}
      <span className={`flex shrink-0 items-center justify-center rounded-full bg-amber font-bold text-white ${className}`}>{count}</span>
      <span className="sr-only"> item{count === "1" ? "" : "s"} to review</span>
    </>
  );
}

const sidebarGroups: { label: string; hrefs: string[] }[] = [
  { label: "Books", hrefs: ["/", "/review", "/ask", "/files"] },
  { label: "Money", hrefs: ["/invoices", "/bank", "/vat", "/payroll", "/reports"] },
  { label: "Buying", hrefs: ["/spending", "/prices", "/shopping"] },
  { label: "Work", hrefs: ["/jobs", "/contacts", "/vehicles"] },
];

function SidebarNav({ pathname, links }: { pathname: string; links: NavLink[] }) {
  const settingsActive = isActive(pathname, "/settings");
  const byHref = new Map(links.map((link) => [link.href, link]));

  return (
    <nav aria-label="Main" className="hidden flex-col min-[900px]:flex">
      {sidebarGroups.map((group, i) => (
        <section key={group.label} aria-labelledby={`nav-group-${group.label.toLowerCase()}`}>
          <p
            id={`nav-group-${group.label.toLowerCase()}`}
            className={`px-4 pb-1 text-[13px] font-bold text-muted ${i === 0 ? "pt-0" : "pt-4"}`}
          >
            {group.label}
          </p>
          <ul className="flex flex-col gap-1">
            {group.hrefs.map((href) => {
              const link = byHref.get(href);
              if (!link) return null;
              const active = isActive(pathname, link.href);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-11 items-center justify-between gap-2 whitespace-nowrap rounded-xl px-4 text-[15px] font-semibold ${
                      active
                        ? "bg-teal-tint text-teal-dark"
                        : "text-ink hover:bg-ground"
                    }`}
                  >
                    <span className="min-w-0 truncate">{link.label}</span>
                    {link.badge ? (
                      <Badge count={link.badge} className="h-6 min-w-6 px-2 text-[13px]" />
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <div className="mt-4 border-t border-border pt-3">
        <Link
          href="/settings"
          aria-current={settingsActive ? "page" : undefined}
          className={`flex h-11 items-center whitespace-nowrap rounded-xl px-4 text-[15px] font-semibold ${
            settingsActive ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"
          }`}
        >
          <span>Settings</span>
        </Link>
      </div>
    </nav>
  );
}

function TabBar({ pathname, links }: { pathname: string; links: NavLink[] }) {
  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-white pb-[env(safe-area-inset-bottom)] min-[900px]:hidden"
    >
      <div className="grid grid-cols-5">
        {links.filter((l) => l.tab).map((link) => {
          const active = isActive(pathname, link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-w-0 flex-col items-center gap-0.5 px-1 py-2 text-[11px] font-bold whitespace-nowrap ${
                active ? "text-teal-dark" : "text-muted"
              }`}
            >
              <span
                aria-hidden="true"
                className={`flex h-1.5 w-8 rounded-full ${active ? "bg-teal" : "bg-transparent"}`}
              />
              <span className="flex min-w-0 items-center gap-1">
                <span className="truncate">{link.tab}</span>
                {link.badge ? <Badge count={link.badge} className="h-4 min-w-4 px-1 text-[10px]" /> : null}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export default function AppNav({ variant = "sidebar" }: { variant?: "sidebar" | "tabs" }) {
  const pathname = usePathname();
  const navLinks = withBadges(useReviewBadge(pathname));

  if (variant === "tabs") return <TabBar pathname={pathname} links={navLinks} />;
  return <SidebarNav pathname={pathname} links={navLinks} />;
}
