import LivePayroll from "@/components/payroll/LivePayroll";

export default function PayrollPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Payroll</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Prepare each month&apos;s pay run from your timesheets, export it for your payroll provider, then confirm what
          was actually paid so your staff costs are in the books. Tax and NI shown here are estimates.
        </p>
      </div>
      <LivePayroll />
    </div>
  );
}
