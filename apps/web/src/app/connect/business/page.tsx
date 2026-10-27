import BusinessForm from "@/components/onboarding/BusinessForm";

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
    </main>
  );
}
