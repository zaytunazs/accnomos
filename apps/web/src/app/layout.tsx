import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";
import SiteShell from "@/components/SiteShell";
import { SIGNED_IN_PROBE } from "@/lib/public-site";

const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Accnomos",
  description: "Books read by AI, approved by you, stored only by you — UK bookkeeping and VAT in your own OneDrive.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: SIGNED_IN_PROBE may add data-signed-in to <html> before React hydrates.
    <html lang="en-GB" className={`${manrope.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: SIGNED_IN_PROBE }} />
      </head>
      <body className="min-h-full flex flex-col">
        <SiteShell>{children}</SiteShell>
      </body>
    </html>
  );
}
