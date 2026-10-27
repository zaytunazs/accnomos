"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavLink = { href: string; label: string; badge?: string; tab?: string };
const links: NavLink[] = [
  { href: "/", label: "Home", tab: "Home" },
  { href: "/review", label: "Review", badge: "3", tab: "Review" },
  { href: "/ask", label: "Ask", tab: "Ask" },
  { href: "/invoices", label: "Invoices" },
  { href: "/bank", label: "Bank" },
  { href: "/vat", label: "VAT return", tab: "VAT" },
  { href: "/jobs", label: "Jobs" },
  { href: "/payroll", label: "Payroll" },
  { href: "/contacts", label: "Contacts" },
  { href: "/vehicles", label: "Vehicles" },
  { href: "/files", label: "Files", tab: "Files" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function SidebarNav({ pathname }: { pathname: string }) {
  const settingsActive = isActive(pathname, "/settings");

  return (
    <nav aria-label="Main" className="hidden flex-col gap-1 min-[900px]:flex">
      {links.map((link) => {
        const active = isActive(pathname, link.href);
        return (
          <Link
            key={link.href}
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
              <span
                aria-label={`${link.badge} items to review`}
                className="flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full bg-amber px-2 text-[13px] font-bold text-white"
              >
                {link.badge}
              </span>
            ) : null}
          </Link>
        );
      })}
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

function TabBar({ pathname }: { pathname: string }) {
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
              aria-label={
                link.badge && !active
                  ? `${link.tab}, ${link.badge} to review`
                  : link.tab
              }
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
                {link.badge ? (
                  <span
                    aria-hidden="true"
                    className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-amber px-1 text-[10px] font-bold text-white"
                  >
                    {link.badge}
                  </span>
                ) : null}
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

  if (variant === "tabs") return <TabBar pathname={pathname} />;
  return <SidebarNav pathname={pathname} />;
}
