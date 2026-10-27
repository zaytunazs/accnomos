"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The one sign-in call to action, same component on every page. It lands on
 * step 1 of the connect wizard (/connect) with a ?next= return, so finishing
 * the wizard brings the user back to the page they came from.
 * Home names the destination ("Connect your OneDrive"); every other page uses "Sign in to see your books".
 */
export default function SignInCta({ home = false, className }: { home?: boolean; className?: string }) {
  const path = usePathname() ?? "/";
  const href =
    path === "/connect" || path.startsWith("/connect/")
      ? "/connect"
      : `/connect?next=${encodeURIComponent(path)}`;
  return (
    <Link
      href={href}
      className={
        className ??
        "shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
      }
    >
      {home ? "Connect your OneDrive" : "Sign in to see your books"}
    </Link>
  );
}
