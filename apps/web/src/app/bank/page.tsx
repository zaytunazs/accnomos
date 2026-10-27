import LiveBank from "@/components/bank/LiveBank";
import ExplainMore from "@/components/ExplainMore";

export const metadata = { title: "Bank statement lines · Accnomos" };

export default function BankPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold tracking-tight">Bank</h1>
          <p className="mt-1 text-[15px] leading-7 text-muted">
            Upload your bank statement CSV and check each payment against your books. Matching never posts
            anything: it records which ledger entry each bank line pays for.
          </p>
        </div>
        <ExplainMore title="How bank matching works" anchor="bank">
          Matching is plain code (amount, date, name), never the AI. Confirm only links a bank line to a posted entry. Layouts follow public formats and have not been checked against real exports.
        </ExplainMore>
      </div>
      <LiveBank />
    </div>
  );
}
