import type { Metadata } from "next";

/** App shell: signed out it shows sample pages, so crawlers stay out. */
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function AccountingLayout({ children }: LayoutProps<"/accounting">) {
  return children;
}
