"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import { disputes, type RtDispute, type RtEvidenceProposal } from "@/lib/disputes";
import { money } from "@/lib/invoices";
import { ukDate } from "@/lib/runtime";

const STATUS: Record<string, string> = {
  OPEN: "Open",
  WAITING_FOR_SELLER_RESPONSE: "Waiting for your answer",
  WAITING_FOR_BUYER_RESPONSE: "Waiting for the customer",
  UNDER_REVIEW: "PayPal is reviewing it",
  RESOLVED: "Closed",
  OTHER: "Open",
};

/** Invoices › PayPal disputes: open disputes on payments Accnomos knows about, evidence built from the books,
 *  sent to PayPal only when the owner taps Send. Hidden while PayPal is not connected and nothing is disputed. */
export default function PayPalDisputes({ account, onChanged }: { account: AccountInfo; onChanged: () => void }) {
  const [rows, setRows] = useState<RtDispute[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const out = await disputes.list(account);
      setRows(out.disputes);
      setProblem(out.problem);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  if (error) return <RuntimeErrorNote message={error} title="Could not check PayPal disputes" />;
  if (!rows || (!rows.length && !problem)) return null;
  return (
    <section aria-label="PayPal disputes" className="space-y-2 rounded-2xl border-2 border-warn-ink/40 bg-warn-bg/40 p-4">
      <h2 className="text-lg font-extrabold">PayPal disputes</h2>
      <p className="text-sm text-muted">
        Accnomos builds the evidence from your books: the invoice as it was emailed, when it was sent and paid, the
        work logged and the audit trail. Nothing goes to PayPal until you press Send.
      </p>
      {problem && <p className="text-sm font-bold text-warn-ink">{problem}</p>}
      <ul className="space-y-2">
        {rows.map((d) => (
          <DisputeRow
            key={d.dispute_id}
            account={account}
            d={d}
            onChanged={() => {
              void load();
              onChanged();
            }}
          />
        ))}
      </ul>
    </section>
  );
}

function DisputeRow({ account, d, onChanged }: { account: AccountInfo; d: RtDispute; onChanged: () => void }) {
  const [proposal, setProposal] = useState<RtEvidenceProposal | null>(d.proposal);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<"build" | "send" | "reverse" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => () => {
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
  }, [pdfUrl]);

  const act = async (kind: "build" | "send" | "reverse", run: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await run();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const sent = proposal?.status === "sent";
  return (
    <li className="rounded-xl border border-border bg-white p-3" aria-label={`Dispute ${d.dispute_id}`}>
      <p className="flex flex-wrap items-center gap-2 text-[15px] font-bold">
        {d.sample && (
          <span className="rounded-full bg-warn-bg px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wide text-warn-ink">
            Sample (demo)
          </span>
        )}
        {d.invoice ? `${d.invoice} · ${d.customer}` : "Not a payment Accnomos knows about"}
        {d.amount_pence !== null && <> · {money(d.amount_pence)} disputed</>}
      </p>
      <p className="text-sm text-muted">
        The customer {d.reason_text}. {STATUS[d.status] ?? d.status}
        {d.respond_by && d.status === "WAITING_FOR_SELLER_RESPONSE" && <> · answer by {ukDate(d.respond_by)}</>}
        {d.opened && <> · opened {ukDate(d.opened)}</>} · PayPal {d.dispute_id}
      </p>
      {!d.invoice && <p className="mt-1 text-sm">Answer this one in PayPal: Accnomos has no record of the payment.</p>}

      {d.can_send_evidence && !sent && !proposal && (
        <div className="mt-2">
          <button
            type="button"
            className={primaryButton}
            disabled={busy !== null}
            onClick={() => act("build", async () => setProposal(await disputes.build(account, d.dispute_id)))}
          >
            {busy === "build" ? "Building the evidence…" : "Build evidence"}
          </button>
        </div>
      )}

      {proposal && (
        <div className="mt-3 rounded-xl bg-ground p-3 text-sm">
          <p className="font-bold">{sent ? "Sent to PayPal" : "Response for PayPal (preview)"}</p>
          <p className="mt-1 whitespace-pre-wrap">{proposal.notes}</p>
          <p className="mt-1 text-[13px] text-muted">
            {proposal.fallback_reason
              ? `Written by code from your books. ${proposal.fallback_reason}`
              : `Drafted by ${proposal.model}; every figure and date checked against your books.`}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={secondaryButton}
              onClick={() =>
                act("build", async () => {
                  const blob = await disputes.pdf(account, d.dispute_id);
                  const url = URL.createObjectURL(blob);
                  setPdfUrl(url);
                  window.open(url, "_blank", "noopener");
                })
              }
            >
              Open evidence PDF
            </button>
            {pdfUrl && (
              <a href={pdfUrl} download={`dispute-${d.dispute_id}.pdf`} className="text-[13px] font-bold text-teal-dark underline">
                Download PDF
              </a>
            )}
            {!sent && d.can_send_evidence && (
              <>
                <button
                  type="button"
                  className={secondaryButton}
                  disabled={busy !== null}
                  onClick={() => act("build", async () => setProposal(await disputes.build(account, d.dispute_id)))}
                >
                  Build again
                </button>
                <button
                  type="button"
                  className={primaryButton}
                  disabled={busy !== null}
                  onClick={() =>
                    act("send", async () => {
                      const out = await disputes.send(account, d.dispute_id);
                      setProposal(out);
                      setNote(out.demo ? "Demo: recorded as sent. Nothing was sent to PayPal." : "Evidence sent to PayPal.");
                      onChanged();
                    })
                  }
                >
                  {busy === "send" ? "Sending…" : d.sample ? "Send to PayPal (demo)" : "Send to PayPal"}
                </button>
              </>
            )}
          </div>
          {sent && proposal.sent_at && (
            <p className="mt-1 text-[13px] text-muted">
              {proposal.demo ? "Demo: not sent to PayPal. " : ""}Sent {ukDate(proposal.sent_at.slice(0, 10))} by {proposal.sent_by}.
            </p>
          )}
        </div>
      )}

      {d.lost && d.reversal && (
        <div className="mt-3 rounded-xl border border-border p-3 text-sm">
          <p className="font-bold">PayPal found for the customer: take the payment back?</p>
          <table className="mt-2 w-full text-[13px] tabular-nums">
            <caption className="sr-only">What approving posts</caption>
            <tbody>
              {d.reversal.journal.map((j, n) => (
                <tr key={n}>
                  <td className="py-0.5">{j.account}</td>
                  <td className="text-right">{j.debit_pence ? `Dr ${money(j.debit_pence)}` : ""}</td>
                  <td className="text-right">{j.credit_pence ? `Cr ${money(j.credit_pence)}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[13px] text-muted">
            The invoice is then open again: raise a credit note or chase it, as you decide.
          </p>
          {d.reversal.can_post ? (
            <button
              type="button"
              className={`${primaryButton} mt-2`}
              disabled={busy !== null}
              onClick={() =>
                act("reverse", async () => {
                  await disputes.reverse(account, d.dispute_id);
                  setNote(`Payment taken back; ${d.invoice} is open again.`);
                  onChanged();
                })
              }
            >
              {busy === "reverse" ? "Posting…" : `Post reversing entry for ${money(d.reversal.amount_pence)}`}
            </button>
          ) : (
            <p className="mt-1 font-bold text-warn-ink">{d.reversal.reason}</p>
          )}
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Could not do that" />}
    </li>
  );
}
