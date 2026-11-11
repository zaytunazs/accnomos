import type { Metadata } from "next";
import PricingView from "@/components/pricing/PricingView";

export const metadata: Metadata = {
  title: "Pricing · Accnomos",
  description: "Three plans from £10 a month ex VAT, a 3-month free trial with no card, and your own AI on every plan.",
};

export default function PricingPage() {
  return <PricingView />;
}
