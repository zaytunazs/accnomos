import ExplainMore from "@/components/ExplainMore";
import LivePaye from "@/components/payroll/LivePaye";
import LivePayroll from "@/components/payroll/LivePayroll";

export const metadata = { title: "Payroll · Accnomos" };

export default function PayrollPage() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Payroll</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Add your employees, calculate each pay run (PAYE, NI, student loans, pensions), approve it into your books, and
            download payslips, RTI files, pension schedules and payroll reports. File with HMRC&apos;s Basic PAYE Tools or your
            payroll provider: direct submission from Accnomos is currently not available.
          </p>
        </div>
        <ExplainMore title="What Accnomos does and does not do for payroll" anchor="payroll">
          Code calculates every figure with HMRC&apos;s 2026-27 rates and specifications. You approve each pay run before it
          posts. FPS and EPS files are built to HMRC&apos;s 2026-27 schema for checking; Accnomos is not HMRC-recognised and never
          submits them.
        </ExplainMore>
      </div>
      <LivePaye />
      <section aria-labelledby="timesheet-estimate" className="flex flex-col gap-4 border-t border-border pt-5">
        <div>
          <h2 id="timesheet-estimate" className="text-[20px] font-extrabold">Quick estimate from timesheets</h2>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            For a payroll provider who runs your payroll: add up the month&apos;s timesheet hours, export them, then record what
            the provider actually paid.
          </p>
        </div>
        <LivePayroll />
      </section>
    </div>
  );
}
