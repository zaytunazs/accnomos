import LiveBank from "@/components/bank/LiveBank";

export default function BankPage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Bank</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Upload your bank statement CSV and check each payment against your books. Matching never posts
          anything: it records which ledger entry each bank line pays for.
        </p>
      </div>
      <LiveBank />
    </div>
  );
}
