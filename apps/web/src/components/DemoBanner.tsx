"use client";

import { usePathname } from "next/navigation";

/** The fictional-company banner: shown on app pages that render sample data, not on policy pages. */
export default function DemoBanner() {
  const path = usePathname() ?? "/";
  if (path.startsWith("/privacy")) return null;
  return (
    <p className="bg-ink px-4 py-2 text-center text-[13px] font-bold text-ground">
      SAMPLE — FICTIONAL COMPANY · Bramblewood Joinery Ltd · demo data only
    </p>
  );
}
