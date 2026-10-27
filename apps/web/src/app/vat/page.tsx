import Link from "next/link";
import SubmitSheet from "@/components/vat/SubmitSheet";
import { box4SampleRows, vatBoxes, vatMeta } from "@/lib/sample-vat";

function EntriesCell({ box, count }: { box: number; count: number }) {
  return (
    <Link
      href="/review"
      aria-label={`View ${count} entries for Box ${box}`}
      className="font-bold text-teal underline underline-offset-2 hover:text-teal-dark"
    >
      {count}
    </Link>
  );
}

export default function VatPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[13px] font-semibold text-muted">
            {vatMeta.period}
          </p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight">
            {vatMeta.title}
          </h1>
        </div>
        <p className="flex items-center gap-2 text-[14px] font-semibold text-muted">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-teal" />
          {vatMeta.status}
        </p>
      </div>

      <div className="flex flex-col gap-6 min-[1000px]:flex-row min-[1000px]:items-start">
        <section
          aria-labelledby="vat-boxes-heading"
          className="min-w-0 flex-1 rounded-2xl border border-border bg-white p-5 sm:p-6"
        >
          <h2 id="vat-boxes-heading" className="sr-only">
            VAT boxes
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[15px]">
              <thead>
                <tr className="border-b border-border text-[13px] font-bold text-muted">
                  <th scope="col" className="px-3 py-2">
                    Box
                  </th>
                  <th scope="col" className="px-3 py-2">
                    What it is
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Amount
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    Entries
                  </th>
                </tr>
              </thead>
              <tbody>
                {vatBoxes.map((row) => (
                  <tr
                    key={row.box}
                    className={`border-t border-border first:border-t-0 ${
                      row.highlight
                        ? "bg-teal-tint"
                        : row.shaded
                          ? "bg-ground"
                          : ""
                    }`}
                  >
                    <th scope="row" className="px-3 py-3 font-extrabold">
                      {row.box}
                    </th>
                    <td className="px-3 py-3">
                      {row.what}
                      {row.warning ? (
                        <span className="text-[13px] font-bold text-warn-ink">
                          {" "}
                          {row.warning}
                        </span>
                      ) : null}
                    </td>
                    <td
                      className={`px-3 py-3 text-right tabular-nums ${
                        row.large
                          ? "text-lg font-extrabold"
                          : "font-bold"
                      }`}
                    >
                      {row.amount}
                    </td>
                    <td className="px-3 py-3 text-right">
                      {row.entries !== null ? (
                        <EntriesCell box={row.box} count={row.entries} />
                      ) : (
                        <span aria-hidden="true" className="text-muted">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="flex w-full flex-col gap-6 min-[1000px]:w-[280px] min-[1000px]:shrink-0">
          <section
            aria-labelledby="box4-heading"
            className="rounded-2xl border border-border bg-white p-5"
          >
            <h2
              id="box4-heading"
              className="text-[15px] font-extrabold tracking-tight"
            >
              Box 4 · VAT reclaimed · {vatMeta.box4Entries} entries
            </h2>
            <ul className="mt-3 flex flex-col gap-2">
              {box4SampleRows.map((entry) => (
                <li
                  key={`${entry.date}-${entry.supplier}`}
                  className="flex items-baseline justify-between gap-2 text-[14px]"
                >
                  <span>
                    {entry.date} {entry.supplier}
                  </span>
                  <span className="font-bold tabular-nums">{entry.vat}</span>
                </li>
              ))}
            </ul>
            <Link
              href="/review"
              className="mt-3 inline-block text-[14px] font-bold text-teal underline underline-offset-2 hover:text-teal-dark"
            >
              See all {vatMeta.box4Entries} entries
            </Link>
          </section>

          <section
            aria-labelledby="vat-warning-heading"
            className="rounded-2xl border border-warn-border bg-warn-bg p-5"
          >
            <h2
              id="vat-warning-heading"
              className="text-[15px] font-extrabold tracking-tight"
            >
              Warning
            </h2>
            <p className="mt-2 text-[14px] leading-6">
              Howdens invoice £2,472 has no VAT number on it. Over £250 needs
              a full VAT invoice.
            </p>
            <p className="mt-2 text-[14px] leading-6">
              <a
                href="#ask-howdens"
                className="font-bold text-teal-dark underline underline-offset-2"
              >
                Ask Howdens for a VAT invoice (draft ready in Outlook)
              </a>{" "}
              or exclude it from this return.
            </p>
          </section>

          <section
            aria-labelledby="reviewer-note-heading"
            className="rounded-2xl bg-ground p-5"
          >
            <h2
              id="reviewer-note-heading"
              className="text-[15px] font-extrabold tracking-tight"
            >
              Reviewer&apos;s note (Muse Spark)
            </h2>
            <p className="mt-2 text-[14px] leading-6 text-muted">
              Box 4 is 18% higher than Q2, mainly the Howdens kitchen order
              (£412 VAT). Otherwise in line with your usual months.
            </p>
          </section>
        </div>
      </div>

      <section
        aria-labelledby="ready-heading"
        className="rounded-2xl border border-border bg-white p-5 sm:p-6"
      >
        <h2 id="ready-heading" className="sr-only">
          Ready to submit
        </h2>
        <p className="text-[15px] leading-7">
          Ready to submit. Figures are calculated by code from{" "}
          {vatMeta.totalEntries} approved entries and tie to your bank. You
          will confirm the legal declaration on the next screen, then the
          return is sent with HMRC&apos;s fraud-prevention headers and the
          receipt is saved to 05 VAT returns/2026-Q3.
        </p>
        <div className="mt-4">
          <SubmitSheet />
        </div>
        <p aria-live="polite" aria-label="Declaration" className="mt-3 text-[13px] text-muted">
          Declaration not yet made — you will confirm it before submission.
        </p>
      </section>
    </div>
  );
}
