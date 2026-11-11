import Link from "next/link";
import type { ReactNode, Ref } from "react";
import ByWhom from "@/components/ByWhom";
import StatusBadge from "@/components/StatusBadge";
import type { Proposal } from "@/lib/sample-review";
import { taxLabel } from "@/lib/region";

/**
 * The card's weight, top to bottom: the supplier and the amount; the evidence (the document, the facts read from
 * it) and any check that failed; the proposed entry; then, lighter, the checker's reasoning, the second reading
 * when it agrees, and which model read it. A verifier that disagrees stays loud (amber), as do failed checks.
 */

/** The card's facts; "VAT" is the books' own tax name outside the UK (lib/region.ts). */
const facts = (tax: string) => [
  { label: "Date", value: (p: Proposal) => p.date },
  { label: `${tax} number`, value: (p: Proposal) => p.vatNumber },
  {
    label: `Net · ${tax} · Total`,
    value: (p: Proposal) => `${p.net} · ${p.vat} · ${p.total}`,
  },
  { label: "Paid by", value: (p: Proposal) => p.paidBy },
];

interface Props {
  proposal: Proposal;
  /** "Always do this for <supplier>": controlled by the parent, which sends the approval. */
  remember?: boolean;
  onRememberChange?: (remember: boolean) => void;
  /** The document thumbnail (opens the original and the crop). */
  media?: ReactNode;
  /** Banners above the card body: needs a look, rule match, Autopilot notes. */
  notices?: ReactNode;
  /** Approve · Edit · Reject, and any pickers. */
  actions?: ReactNode;
  /** The keyboard's current card: focusable, and outlined. */
  cardRef?: Ref<HTMLElement>;
  active?: boolean;
  onFocus?: () => void;
}

export default function ProposalCard({ proposal, remember, onRememberChange, media, notices, actions, cardRef, active = false, onFocus }: Props) {
  return (
    <section
      ref={cardRef}
      tabIndex={-1}
      onFocus={onFocus}
      aria-labelledby={`proposal-${proposal.id}`}
      aria-current={active ? "true" : undefined}
      className={`min-w-0 scroll-mt-24 rounded-2xl border bg-white p-4 outline-none sm:p-6 ${
        active ? "border-teal ring-2 ring-teal" : "border-border"
      }`}
    >
      {notices && <div className="mb-4 flex flex-col gap-2">{notices}</div>}
      <div className="flex flex-col gap-5 sm:flex-row">
        {media ?? (
          <div
            aria-hidden="true"
            className="flex h-[150px] w-full shrink-0 items-center justify-center rounded-xl bg-ground text-sm font-semibold text-muted sm:h-[230px] sm:w-[180px]"
          >
            Receipt
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h2
            id={`proposal-${proposal.id}`}
            className="break-words text-[22px] font-extrabold leading-tight tracking-tight sm:text-2xl"
          >
            {proposal.supplier} · <span className="tabular-nums">{proposal.total}</span>
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
            <StatusBadge tone="neutral">{proposal.confidence}</StatusBadge>
            <span className="text-[13px] text-muted">{proposal.source}</span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {facts(taxLabel()).map((fact) => (
              <div key={fact.label} className="min-w-0">
                <dt className="text-[13px] font-semibold text-muted">
                  {fact.label}
                </dt>
                <dd className="mt-0.5 break-words text-[15px] font-bold">
                  {fact.value(proposal)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      {proposal.failedChecks && proposal.failedChecks.length > 0 && (
        <ul aria-label="Checks that need you" className="mt-4 flex flex-col gap-1 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink">
          {proposal.failedChecks.map((c) => (
            <li key={c.text} className="flex gap-2">
              <span aria-hidden="true" className="font-bold">{c.warn ? "!" : "✕"}</span>
              <span>
                <span className="sr-only">{c.warn ? "Warning: " : "Check failed: "}</span>
                {c.text}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 overflow-hidden rounded-xl border border-border">
        <p className="bg-ground px-4 py-2 text-[13px] font-bold text-muted">
          Proposed entry / What it means
        </p>
        {/* Phone: stacked lines. Wider screens: the two-column table. */}
        <ul className="flex flex-col divide-y divide-border min-[560px]:hidden">
          {proposal.lines.map((line) => (
            <li key={line.account} className="px-4 py-3">
              <p className="text-[15px] font-bold">{line.account}</p>
              <p className="mt-0.5 text-[14px] text-muted">{line.meaning}</p>
            </li>
          ))}
        </ul>
        <table className="hidden w-full text-left text-[15px] min-[560px]:table">
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

      {/* The checker's reasoning and the second reading: the technical trail, lighter than the facts above. A
          verifier that disagrees keeps the amber box. */}
      {proposal.reviewerNote && (
        <p className="mt-4 break-words rounded-xl bg-ground px-4 py-3 text-[14px] leading-6 text-muted">
          {proposal.reviewerNote}
        </p>
      )}
      <div
        className={`mt-3 break-words ${
          proposal.verifierTone === "differ"
            ? "rounded-xl border border-warn-border bg-warn-bg p-4 text-[15px] leading-7 text-warn-ink"
            : "px-1 text-[13px] leading-5 text-muted"
        }`}
      >
        <p>{proposal.verifierNote}</p>
        {proposal.verifierDiffs && proposal.verifierDiffs.length > 0 && (
          <table className="mt-2 w-full table-fixed text-left text-[14px]">
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
                  <td className="break-words py-1 pr-3">{d.field}</td>
                  <td className="break-words py-1 pr-3 font-bold">{d.extractor}</td>
                  <td className="break-words py-1 font-bold">{d.verifier}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ByWhom className="mt-2 px-1" code="Checked by code" ai="read by AI" />
      {proposal.servedLine && (
        <p data-testid="served-by" className="mt-1 break-words px-1 text-[12px] leading-5 text-muted">
          {proposal.servedLine} ·{" "}
          <Link href="/models" className="text-teal-dark underline underline-offset-2 hover:text-teal">
            AI models at work
          </Link>
        </p>
      )}

      {onRememberChange && (
        <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-semibold">
          <input
            type="checkbox"
            className="h-5 w-5 shrink-0 accent-teal"
            checked={remember ?? false}
            onChange={(e) => onRememberChange(e.target.checked)}
          />
          Always do this for {proposal.supplier}
        </label>
      )}
      {actions && <div className="mt-4 flex flex-col gap-3">{actions}</div>}
    </section>
  );
}
