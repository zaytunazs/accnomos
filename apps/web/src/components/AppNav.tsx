"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/review", label: "Review", badge: "3" },
  { href: "/ask", label: "Ask" },
  { href: "/vat", label: "VAT return" },
  { href: "/files", label: "Files" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function AppNav() {
  const pathname = usePathname();

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
    </nav>
  );
}
