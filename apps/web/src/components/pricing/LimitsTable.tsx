import { LIMIT_ROWS, PLAN_CODES, PLAN_NAMES, limitCell, type RtPlan } from "@/lib/billing";

/** The limits table of docs/billing/PLANS_AND_CONTRACT.md: one row per limit, one column per plan (live values from GET /plans when it answers). */
export default function LimitsTable({ plans }: { plans?: RtPlan[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-border bg-white">
      <table className="w-full min-w-[34rem] border-collapse text-left text-[15px]" data-limits-table="">
        <caption className="sr-only">What each plan includes</caption>
        <thead>
          <tr className="border-b border-border bg-ground">
            <th scope="col" className="px-4 py-3 font-bold">Limit, per month unless stated</th>
            {PLAN_CODES.map((c) => (
              <th key={c} scope="col" className="px-4 py-3 font-extrabold">{PLAN_NAMES[c]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {LIMIT_ROWS.map((row) => (
            <tr key={row.label} className="border-b border-border last:border-0">
              <th scope="row" className="px-4 py-3 font-semibold">
                {row.label}
                {row.note && <span className="block text-xs font-normal text-muted">{row.note}</span>}
              </th>
              {PLAN_CODES.map((c) => (
                <td key={c} className="px-4 py-3" data-plan={c}>{limitCell(row, c, plans)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
