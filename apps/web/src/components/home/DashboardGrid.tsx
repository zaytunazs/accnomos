import Link from "next/link";

const cards: { title: string; body: string; action: string; href: string }[] = [
  {
    title: "Review",
    body: "Proposals the AI has read and checked, waiting for your decision. Nothing posts until you say so.",
    action: "Open Review",
    href: "/review",
  },
  {
    title: "Invoices",
    body: "Send invoices, chase late payers and record payment when the money lands.",
    action: "Open Invoices",
    href: "/invoices",
  },
  {
    title: "Bank",
    body: "Bring in a statement and match each line to an approved entry.",
    action: "Open Bank",
    href: "/bank",
  },
  {
    title: "VAT return",
    body: "The 9-box return, worked out by code from your approved entries.",
    action: "Open VAT return",
    href: "/vat",
  },
];

/** Signed-in dashboard: one grid, every card the same height and padding, one button each. */
export default function DashboardGrid() {
  return (
    <section aria-label="Dashboard" className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2">
      {cards.map((c) => (
        <div
          key={c.title}
          className="flex h-full flex-col rounded-2xl border border-border bg-white p-5"
        >
          <h2 className="text-lg font-extrabold tracking-tight">{c.title}</h2>
          <p className="mt-1 text-sm leading-6 text-muted">{c.body}</p>
          <div className="mt-auto pt-4">
            <Link
              href={c.href}
              className="flex h-11 w-full items-center justify-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
            >
              {c.action}
            </Link>
          </div>
        </div>
      ))}
    </section>
  );
}
