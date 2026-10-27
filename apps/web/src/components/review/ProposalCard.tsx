import type { Proposal } from "@/lib/sample-review";

const facts = [
  { label: "Date", value: (p: Proposal) => p.date },
  { label: "VAT number", value: (p: Proposal) => p.vatNumber },
  {
    label: "Net · VAT · Total",
    value: (p: Proposal) => `${p.net} · ${p.vat} · ${p.total}`,
  },
  { label: "Paid by", value: (p: Proposal) => p.paidBy },
];

export default function ProposalCard({ proposal }: { proposal: Proposal }) {
  return (
    <section
      aria-labelledby={`proposal-${proposal.id}`}
      className="rounded-2xl border border-border bg-white p-5 sm:p-6"
    >
      <div className="flex flex-col gap-5 sm:flex-row">
        <div
          aria-hidden="true"
          className="flex h-[230px] w-[180px] shrink-0 items-center justify-center rounded-xl bg-ground text-sm font-semibold text-muted"
        >
          Receipt
        </div>
        <div className="min-w-0 flex-1">
          <h2
            id={`proposal-${proposal.id}`}
            className="text-xl font-extrabold tracking-tight"
          >
            {proposal.supplier} · {proposal.total}
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            <span className="rounded-full bg-teal-tint px-3 py-1 text-[13px] font-bold text-teal-dark">
              {proposal.confidence}
            </span>
            <span className="rounded-full bg-ground px-3 py-1 text-[13px] font-semibold text-muted">
              {proposal.source}
            </span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt className="text-[13px] font-semibold text-muted">
                  {fact.label}
                </dt>
                <dd className="mt-0.5 text-[15px] font-bold">
                  {fact.value(proposal)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <div className="mt-5 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-left text-[15px]">
          <caption className="bg-ground px-4 py-2 text-left text-[13px] font-bold text-muted">
            Proposed entry / What it means
          </caption>
          <tbody>
            {proposal.lines.map((line) => (
              <tr
                key={line.account}
                className="border-t border-border first:border-t-0"
              >
                <td className="px-4 py-3 font-bold">{line.account}</td>
                <td className="px-4 py-3 text-muted">{line.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 rounded-xl bg-ground p-4 text-[15px] leading-7">
        {proposal.reviewerNote}
      </p>
      <div
        className={`mt-3 rounded-xl p-4 text-[15px] leading-7 ${
          proposal.verifierTone === "differ"
            ? "border border-warn-border bg-warn-bg text-warn-ink"
            : proposal.verifierTone === "none"
              ? "bg-ground text-muted"
              : "bg-teal-tint text-teal-dark"
        }`}
      >
        <p>{proposal.verifierNote}</p>
        {proposal.verifierDiffs && proposal.verifierDiffs.length > 0 && (
          <table className="mt-2 w-full text-left text-[14px]">
            <thead>
              <tr>
                <th className="py-1 pr-3 font-semibold">Field</th>
                <th className="py-1 pr-3 font-semibold">First reading</th>
                <th className="py-1 font-semibold">Second reading</th>
              </tr>
            </thead>
            <tbody>
              {proposal.verifierDiffs.map((d) => (
                <tr key={d.field} className="border-t border-warn-border">
                  <td className="py-1 pr-3">{d.field}</td>
                  <td className="py-1 pr-3 font-bold">{d.extractor}</td>
                  <td className="py-1 font-bold">{d.verifier}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          className="h-11 rounded-xl bg-teal px-6 text-[15px] font-bold text-white hover:bg-teal-dark"
        >
          Approve
        </button>
        <button
          type="button"
          className="h-11 rounded-xl border border-border bg-white px-6 text-[15px] font-bold hover:bg-ground"
        >
          Edit
        </button>
        <button
          type="button"
          className="h-11 rounded-xl border border-border bg-white px-6 text-[15px] font-bold hover:bg-ground"
        >
          Reject
        </button>
      </div>
      <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-semibold">
        <input
          type="checkbox"
          className="h-5 w-5 accent-teal"
        />
        Always do this for Screwfix
      </label>
    </section>
  );
}
