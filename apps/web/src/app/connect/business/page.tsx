import BusinessForm from "@/components/onboarding/BusinessForm";
import InvoiceProfileForm from "@/components/invoices/InvoiceProfileForm";

export const metadata = { title: "About your business · Accnomos" };

export default function BusinessPage() {
  return (
    <main className="mx-auto max-w-xl px-4 py-10">
      <p className="text-xs font-bold uppercase tracking-wider text-teal-dark">Step 3 of 4</p>
      <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-ink">About your business</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">
        This shapes your VAT return and where your books live. It stays on this device.
      </p>
      <BusinessForm />
      <div className="mt-8">
        <p className="mb-2 text-sm text-muted">
          Optional, for sending invoices: you can also do this later in Settings.
        </p>
        <InvoiceProfileForm card="rounded-2xl border border-border bg-white p-4" heading="text-[17px] font-extrabold text-ink" />
      </div>
    </main>
  );
}
