import LiveShopping from "@/components/spending/LiveShopping";

export const metadata = { title: "Shopping list · Accnomos" };

export default function Page() {
  return (
    <div className="flex flex-col gap-5">
      <div className="min-w-0">
        <h1 className="text-3xl font-extrabold tracking-tight">Shopping list</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Add what you need; Accnomos finds it in your past receipts, asks which one you mean or for the sizes, and suggests the cheapest supplier you have used. The list is kept in your OneDrive.
        </p>
      </div>
      <LiveShopping />
    </div>
  );
}
