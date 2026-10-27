import Link from "next/link";
import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import PrintButton from "@/components/PrintButton";
import SignedOutOnly from "@/components/SignedOutOnly";
import BoxExplain from "@/components/vat/BoxExplain";
import SubmitSheet from "@/components/vat/SubmitSheet";
import LiveVat from "@/components/vat/LiveVat";
import ConnectHmrc from "@/components/vat/ConnectHmrc";
import VatDeadlineStrip from "@/components/vat/VatDeadlineStrip";
import { HomeData } from "@/components/home/HomeData";
import { box4SampleRows, vatBoxes, vatMeta } from "@/lib/sample-vat";

const SAMPLE_BOX5 = "£2,140 to pay · due 7 Nov · 12 days left";

export const metadata = { title: "VAT return · Accnomos" };

function EntriesCell({ box, count }: { box: number; count: number }) {
  return (
    <Link
      href="/review"
      aria-label={`View ${count} entries for Box ${box}`}
      className="whitespace-nowrap font-bold text-teal underline underline-offset-2 hover:text-teal-dark"
    >
      {count}
    </Link>
  );
}

export default function VatPage() {
  return (
    <div data-print-page className="flex flex-col gap-6">
      <HomeData>
        <VatDeadlineStrip />
      </HomeData>
      <PageHeader
        title="VAT return"
        description="Your 9-box return, worked out by code from the entries you approved."
        action={
          <div className="flex items-center gap-2">
            <span className="print:hidden">
              <PrintButton />
            </span>
            <Explain title="How each box is worked out">
              <p>
                Every box is calculated by code from the ledger events you approved — no model is
                involved. Only lines with VAT codes S, R, Z, E or N count; O (outside the scope
                of UK VAT) is left out. Undoing an entry nets it off through its reversing event.
              </p>
              <ul className="list-disc space-y-1 pl-5">
                <li><strong>Box 1</strong> — VAT on your sales in the period.</li>
                <li><strong>Box 2</strong> — VAT on acquisitions from Northern Ireland and the EU. Zero if you only trade in Great Britain.</li>
                <li><strong>Box 3</strong> — Box 1 plus Box 2.</li>
                <li><strong>Box 4</strong> — VAT reclaimed on your purchases in the period.</li>
                <li><strong>Box 5</strong> — what you owe: Box 3 minus Box 4.</li>
                <li><strong>Box 6</strong> — total sales excluding VAT, in whole pounds.</li>
                <li><strong>Box 7</strong> — total purchases excluding VAT, in whole pounds.</li>
                <li><strong>Boxes 8 and 9</strong> — goods supplied to, or acquired from, Northern Ireland and the EU. Zero if you only trade in Great Britain.</li>
              </ul>
              <p>
                Boxes 1 to 5 are kept to the penny; Boxes 6 to 9 are whole pounds, rounded down.
                Tap an entry count to see the entries behind a box on the Review page.
              </p>
            </Explain>
          </div>
        }
      />
      <LiveVat />
      <ConnectHmrc />

      {/* Signed out only: once signed in, the page is the live card (with its period picker) and nothing else. */}
      <SignedOutOnly>
        <div className="flex flex-col gap-6">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] font-medium text-muted">
            <span>SAMPLE — FICTIONAL COMPANY · a mock-up of a finished return ({vatMeta.period}). Sign in to see yours.</span>
            <span className="hidden print:inline">Estimate until submitted.</span>
            <span className="flex items-center gap-2 font-semibold whitespace-nowrap">
              <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-teal" />
              {vatMeta.status}
            </span>
          </p>
          <div className="flex flex-col gap-6 min-[1000px]:flex-row min-[1000px]:items-start">
            <section
              aria-labelledby="vat-boxes-heading"
              className="min-w-0 flex-1 rounded-2xl border border-border bg-white p-5 sm:p-6"
            >
              <h2 id="vat-boxes-heading" className="sr-only">
                VAT boxes
              </h2>
              {/* Phone: one card per box. Wider screens: the 9-box table. */}
              <ul className="flex flex-col gap-3 sm:hidden">
                {vatBoxes.map((row) => (
                  <li
                    key={row.box}
                    className={`rounded-xl border p-4 ${
                      row.highlight
                        ? "border-teal bg-teal-tint"
                        : row.shaded
                          ? "border-border bg-ground"
                          : "border-border bg-white"
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="flex min-w-0 items-center gap-1 text-[15px] font-extrabold">
                        <span>
                          Box {row.box} · {row.what}
                        </span>
                        <BoxExplain
                          box={row.box}
                          label={row.what}
                          entries={row.entries}
                          extra={row.box === 5 ? SAMPLE_BOX5 : undefined}
                        />
                      </p>
                    </div>
                    <div className="mt-1 flex items-baseline justify-between gap-2">
                      <p
                        className={`tabular-nums ${row.large ? "text-lg font-extrabold" : "font-bold"}`}
                      >
                        {row.amount}
                      </p>
                      {row.entries !== null ? (
                        <EntriesCell box={row.box} count={row.entries} />
                      ) : (
                        <span aria-hidden="true" className="text-muted">
                          —
                        </span>
                      )}
                    </div>
                    {row.warning ? (
                      <p className="mt-1 text-[13px] font-bold text-warn-ink">{row.warning}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
              <div className="hidden overflow-x-auto sm:block">
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
                      <th scope="col" className="px-3 py-2">
                        <span className="sr-only">Explain</span>
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
                        <td className="px-3 py-3 text-right">
                          <BoxExplain
                            box={row.box}
                            label={row.what}
                            entries={row.entries}
                            extra={row.box === 5 ? SAMPLE_BOX5 : undefined}
                          />
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
              receipt is saved to 06 VAT returns/2026-Q3.
            </p>
            <div className="mt-4">
              <SubmitSheet />
            </div>
            <p aria-live="polite" aria-label="Declaration" className="mt-3 text-[13px] text-muted">
              Declaration not yet made — you will confirm it before submission.
            </p>
          </section>
        </div>
      </SignedOutOnly>
    </div>
  );
}
