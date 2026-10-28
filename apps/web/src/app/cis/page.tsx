import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import LiveCis from "@/components/cis/LiveCis";

export const metadata = { title: "CIS · Accnomos" };

export default function CisPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="CIS"
        description="Construction Industry Scheme deductions, statements and monthly returns, and the VAT reverse charge for building work."
        action={
          <Explain title="How CIS works here">
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Subcontractor</strong> — your invoices show the deduction on labour only (materials and VAT are left out). A payment received net of the deduction pays the invoice in full; the deduction is tax paid on account.</li>
              <li><strong>Statements</strong> — your AI reads a contractor&apos;s monthly statement, code checks the figures, and you approve. The year totals come from the statements.</li>
              <li><strong>Contractor</strong> — code works out each deduction from the subcontractor&apos;s status and prepares the CIS300 figures and a file. Accnomos never submits it: you file through HMRC&apos;s CIS online service or CIS software.</li>
              <li><strong>Reverse charge</strong> — no VAT on invoices to VAT- and CIS-registered customers; the customer accounts for it.</li>
            </ul>
          </Explain>
        }
      />
      <LiveCis />
    </div>
  );
}
