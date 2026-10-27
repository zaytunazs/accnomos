import ExplainMore from "@/components/ExplainMore";
import LivePayroll from "@/components/payroll/LivePayroll";

export const metadata = { title: "Payroll pay run · Accnomos" };

export default function PayrollPage() {
  return (
    <div data-print-page className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Payroll</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Prepare each month&apos;s pay run from your timesheets, export it for your payroll provider, then confirm what
            was actually paid so your staff costs are in the books. Tax and NI shown here are estimates.
          </p>
        </div>
        <ExplainMore title="Why pay figures are estimates" anchor="payroll">
          Tax and NI are a rough guide (monthly pay, 1257L month-1, England/NI, category A). Your provider works out the real amounts; Confirm posts the actuals you type in. Accnomos never files RTI.
        </ExplainMore>
      </div>
      <LivePayroll />
    </div>
  );
}
