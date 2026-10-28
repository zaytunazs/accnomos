import LiveSpending from "@/components/spending/LiveSpending";

export const metadata = { title: "Spending · Accnomos" };

export default function Page() {
  return (
    <div className="flex flex-col gap-5">
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold tracking-tight">Spending</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Where your money went in a month, a quarter or any span: by category, supplier and item, against the period before, with regular costs and unusual one-offs. Figures are calculated by code from your approved purchases; your AI writes the summary and every figure in it is checked.
        </p>
      </div>
      <LiveSpending />
    </div>
  );
}
