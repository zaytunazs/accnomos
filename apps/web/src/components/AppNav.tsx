"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/review", label: "Review", badge: "3" },
  { href: "/invoices", label: "Invoices" },
  { href: "/ask", label: "Ask" },
  { href: "/bank", label: "Bank" },
  { href: "/vat", label: "VAT return" },
  { href: "/jobs", label: "Jobs" },
  { href: "/payroll", label: "Payroll" },
  { href: "/contacts", label: "Contacts" },
  { href: "/vehicles", label: "Vehicles" },
  { href: "/files", label: "Files" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function AppNav() {
  const pathname = usePathname();

  const settingsActive = isActive(pathname, "/settings");

  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {links.map((link) => {
        const active = isActive(pathname, link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`flex h-11 items-center justify-between rounded-xl px-4 text-[15px] font-semibold ${
              active
                ? "bg-teal-tint text-teal-dark"
                : "text-ink hover:bg-ground"
            }`}
          >
            <span>{link.label}</span>
            {link.badge ? (
              <span
                aria-label={`${link.badge} items to review`}
                className="flex h-6 min-w-6 items-center justify-center rounded-full bg-amber px-2 text-[13px] font-bold text-white"
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
          className={`flex h-11 items-center rounded-xl px-4 text-[15px] font-semibold ${
            settingsActive ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"
          }`}
        >
          <span>Settings</span>
        </Link>
      </div>
    </nav>
  );
}
