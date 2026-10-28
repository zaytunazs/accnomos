import Link from "next/link";
import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import ReportsExports from "@/components/reports/ReportsExports";

export const metadata = { title: "Reports & exports · Accnomos" };

export default function ReportsExportsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Reports & exports"
        description="Every report your accountant asks for, HMRC's VAT return layout, and files that import into Xero, QuickBooks, Sage and FreeAgent."
        action={
          <Explain title="How reports and exports work">
            <p>
              Every figure is worked out by code from your approved ledger entries; no model is involved. Previewing or
              downloading a report changes nothing; <em>Save to 07 Reports</em> writes one file to your OneDrive and posts
              nothing to your books.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Groups</strong> follow Xero&apos;s report list, so an accountant finds each one where they expect it.</li>
              <li><strong>UK VAT return</strong> uses HMRC&apos;s box numbers and wording, with the entries behind each box and the digital-links trail.</li>
              <li><strong>Import files</strong> follow each package&apos;s published template. Import journals or invoices and bills for a period, never both.</li>
              <li><strong>Account mapping</strong> says where each of your accounts lands in the other package; fill in any marked Check or Unmapped.</li>
            </ul>
          </Explain>
        }
      />
      <p className="text-[15px]">
        <Link href="/reports" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
          Back to the reports overview
        </Link>
      </p>
      <ReportsExports />
    </div>
  );
}
