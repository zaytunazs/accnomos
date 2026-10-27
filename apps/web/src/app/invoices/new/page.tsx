import { Suspense } from "react";
import Link from "next/link";
import InvoiceForm from "@/components/invoices/InvoiceForm";

export const metadata = { title: "New invoice · Accnomos" };

export default function NewInvoicePage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <Link href="/invoices" className="text-sm font-bold text-teal-dark">← Invoices</Link>
        <h1 className="mt-1 text-3xl font-extrabold tracking-tight">Invoice</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Saved as a draft first. Your business details, logo and bank details come from the{" "}
          <Link href="/settings#invoice-profile" className="font-bold text-teal-dark">invoice profile</Link>.
        </p>
      </div>
      {/* useSearchParams (?id= to change a draft) needs a Suspense boundary in a static export */}
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <InvoiceForm />
      </Suspense>
    </div>
  );
}
