import type { Metadata } from "next";
import { ProblemCard } from "@/components/ErrorDetails";

export const metadata: Metadata = { title: "Not found · Accnomos" };

/**
 * Unknown paths (the static host serves this as 404.html, see public/.htaccess).
 * A wrong address is never a runtime fault, so there is no reference to quote.
 */
export default function NotFound() {
  return (
    <ProblemCard
      title="Page not found"
      body="That address isn't a page in Accnomos — check for a typo, or head back home. Nothing is lost."
    />
  );
}
