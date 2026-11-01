import type { Metadata } from "next";

/** App shell: signed out it shows a sample page, so crawlers stay out. */
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function VehiclesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
