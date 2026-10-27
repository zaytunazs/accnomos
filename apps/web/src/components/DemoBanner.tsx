"use client";

import { usePathname } from "next/navigation";
import { useSignedIn } from "@/lib/signed-in";

/** Pages whose content is sample data until the user signs in. */
const SAMPLE_PAGES = ["/", "/review", "/ask", "/vat", "/files"];

function isSamplePage(path: string): boolean {
  return SAMPLE_PAGES.some((p) =>
    p === "/" ? path === "/" : path === p || path.startsWith(`${p}/`),
  );
}

/**
 * The fictional-company banner. Shown only while sample data is on screen:
 * never on policy, onboarding or settings pages, and never once this device
 * is signed in (live pages label their own sample fallbacks inline).
 */
export default function DemoBanner() {
  const path = usePathname() ?? "/";
  const signedIn = useSignedIn(path);

  if (!isSamplePage(path)) return null;
  if (signedIn === true) return null;
  return (
    <aside aria-label="Sample data">
      <p className="bg-ink px-4 py-2 text-center text-[13px] font-bold text-ground">
        SAMPLE — FICTIONAL COMPANY · demo data only
      </p>
    </aside>
  );
}
