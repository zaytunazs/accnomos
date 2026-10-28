import Link from "next/link";
import type { RtSchemeView } from "@/lib/runtime";

const uk = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};
const gbp = (pounds: string) => `£${Number(pounds).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** How the boxes on the VAT page were worked out under the business's VAT scheme(s): every figure is the runtime's. */
export default function SchemeNote({ scheme }: { scheme: RtSchemeView }) {
  const split = scheme.segments.length > 1;
  return (
    <section aria-labelledby="vat-scheme-note" className="mt-4 rounded-xl border border-border bg-ground p-4 text-[15px]">
      <h3 id="vat-scheme-note" className="font-extrabold">
        How these boxes were worked out
      </h3>
      <p className="mt-1">{scheme.summary}</p>
      {split && <p className="mt-1 text-sm text-muted">The scheme changes in this period: one calculation for each part, added together.</p>}
      <ul className="mt-2 space-y-2">
        {scheme.segments.map((seg) => (
          <li key={seg.start} className="rounded-lg bg-white p-3">
            {split && (
              <p className="text-sm font-bold">
                {uk(seg.start)} – {uk(seg.end)}: {seg.label}
              </p>
            )}
            {seg.scheme === "flat_rate" ? (
              <>
                <ul className="text-sm">
                  {seg.calcs.map((c) => (
                    <li key={c.start} data-testid="flat-rate-calc">
                      {c.percent}% of {gbp(c.turnover)} turnover including VAT = <strong>{gbp(c.tax)}</strong>
                      {seg.calcs.length > 1 ? ` (${uk(c.start)} – ${uk(c.end)})` : ""}
                      {c.first_year ? " · first-year 1% off" : ""}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-muted">
                  {seg.limited_cost_source === "auto"
                    ? `Limited cost test: goods ${gbp(seg.relevant_goods ?? "0")} against 2% of turnover or ${gbp(seg.limited_cost_cap ?? "0")} — ${
                        seg.limited_cost ? "a limited cost business, so 16.5%" : "not a limited cost business"
                      }.`
                    : seg.limited_cost
                      ? "Limited cost business (your setting): 16.5%."
                      : "Not a limited cost business (your setting)."}
                  {Number(seg.capital_vat ?? 0) > 0 ? ` VAT on capital goods claimed in box 4: ${gbp(seg.capital_vat!)}.` : ""}
                  {" "}No other VAT on purchases is claimed on the flat rate.
                </p>
              </>
            ) : seg.cash_basis ? (
              <p className="text-sm">
                VAT on {seg.payments} payment{seg.payments === 1 ? "" : "s"} received or made in this period, not on invoice dates.
                {Number(seg.unpaid_brought_in_vat) !== 0
                  ? ` Leaving the scheme: VAT of ${gbp(seg.unpaid_brought_in_vat)} on documents still unpaid is included.`
                  : ""}
              </p>
            ) : (
              <p className="text-sm">VAT on invoices issued and received in this period.</p>
            )}
          </li>
        ))}
      </ul>
      {scheme.annual && (
        <div className="mt-3 rounded-lg bg-white p-3 text-sm" data-testid="annual-accounting">
          <p className="font-bold">
            Annual accounting: return and balancing payment due {uk(scheme.annual.return_due)}
          </p>
          {scheme.annual.instalments.length > 0 ? (
            <>
              <p className="mt-1">
                {scheme.annual.instalments.length} interim payment{scheme.annual.instalments.length === 1 ? "" : "s"} of{" "}
                {gbp(scheme.annual.instalments[0].amount)} (first due {uk(scheme.annual.instalments[0].due)}), {gbp(scheme.annual.instalments_total)} in all.
              </p>
              <p className="mt-1">
                {scheme.annual.balancing_direction === "pay"
                  ? `Balancing payment so far: ${gbp(scheme.annual.balancing)} to pay with the return.`
                  : scheme.annual.balancing_direction === "refund"
                    ? `So far the instalments are ${gbp(scheme.annual.balancing)} more than box 5: HMRC refunds the difference after the return.`
                    : "So far the instalments match box 5."}
              </p>
            </>
          ) : (
            <p className="mt-1 text-muted">
              {scheme.annual.basis_known
                ? "No interim payments for this period."
                : "Add the figure from HMRC's letter in Settings › VAT scheme to see the interim payments."}
            </p>
          )}
        </div>
      )}
      <p className="mt-2 text-xs text-muted">
        HMRC rules checked {scheme.checked}:{" "}
        <a href={scheme.sources.boxes} target="_blank" rel="noreferrer" className="underline underline-offset-2">
          VAT Notice 700/12
        </a>
        . <Link href="/settings#settings-vat-scheme" className="font-bold underline underline-offset-2">Change your VAT scheme</Link>
      </p>
    </section>
  );
}
