import LivePrices from "@/components/spending/LivePrices";

export const metadata = { title: "Cheaper options · Accnomos" };

export default function Page() {
  return (
    <div className="flex flex-col gap-5">
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold tracking-tight">Cheaper options</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Where you paid less for the same or an equivalent item, and what buying at that price would save at your usual volume. Prices come from receipts and bills in your books; code reads sizes and packs and does the maths.
        </p>
      </div>
      <LivePrices />
    </div>
  );
}
