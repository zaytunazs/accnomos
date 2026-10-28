"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import AppShell from "@/components/AppShell";
import MarketingShell from "@/components/marketing/MarketingShell";
import { isPublicPath } from "@/lib/public-site";
import { useSignedIn } from "@/lib/signed-in";

/**
 * The one switch between the two shells. Signed-out visitors on the public routes (lib/public-site.ts) get the
 * marketing shell: its own top menu, footer and the "Ask about Accnomos" chat. Everything else, and every route
 * once this device is signed in, gets the app shell (AppShell.tsx: sidebar, tab bar and the signed-in header).
 * The two never share chrome, so the signed-in header can change without touching the public site.
 */
export default function SiteShell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const signedIn = useSignedIn(path);
  if (isPublicPath(path) && signedIn !== true) return <MarketingShell path={path}>{children}</MarketingShell>;
  return <AppShell>{children}</AppShell>;
}
