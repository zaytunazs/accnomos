import { Suspense } from "react";
import BusinessForm from "@/components/onboarding/BusinessForm";
import ConnectSteps from "@/components/connect/ConnectSteps";

export const metadata = { title: "About your business · Accnomos" };

export default function BusinessPage() {
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <ConnectSteps current={3} />
      <h1 className="mt-4 text-3xl font-extrabold tracking-tight text-ink">About your business</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        This shapes your VAT return and where your books live. It stays on this device.
      </p>
      <Suspense fallback={<p className="mt-6 text-sm text-muted">Loading…</p>}>
        <BusinessForm />
      </Suspense>
    </div>
  );
}
