"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { fieldInput, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { balanceOf } from "@/components/invoices/PaymentDialogs";
import { TestModeBadge } from "@/components/settings/OnlinePayments";
import { RuntimeErrorNote } from "@/components/States";
import { money, parsePounds } from "@/lib/invoices";
import { runtime, ukDate, type RtFoundPayment, type RtInvoice, type RtPayProvider, type RtProviderStatus } from "@/lib/runtime";

const LABEL: Record<RtPayProvider, string> = { stripe: "Stripe", paypal: "PayPal", paypalme: "PayPal.me" };

/** What a link is for: the total of a draft, the balance of a sent invoice. */
export const linkAmount = (i: RtInvoice) => (i.status === "draft" ? i.total_pence : balanceOf(i));

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="text-[13px] font-bold text-teal-dark hover:underline"
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        } catch {
          window.prompt("Copy the payment link", text);
        }
      }}
    >
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

/** The link on an invoice row: the URL, Copy, and Remove. */
export function PayOnlineLine({
  account, invoice, onChanged,
}: { account: AccountInfo; invoice: RtInvoice; onChanged: (inv: RtInvoice, message: string) => void }) {
  const link = invoice.payment_link;
  const [error, setError] = useState<string | null>(null);
  if (!link) return null;
  const stale = linkAmount(invoice) !== link.amount_pence && invoice.status !== "paid";
  return (
    <div className="mt-2 rounded-xl bg-ground px-3 py-2 text-sm" aria-label={`Payment link for ${invoice.number}`} role="group">
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-bold text-ink">Pay online · {LABEL[link.provider]} · {money(link.amount_pence)}</span>
        {link.test_mode && <TestModeBadge />}
        {stale && <span className="font-bold text-warn-ink">Not the amount owed now: make a new link</span>}
      </p>
      <p className="mt-1 flex flex-wrap items-center gap-3">
        <a href={link.url} target="_blank" rel="noopener noreferrer" className="min-w-0 break-all text-teal-dark underline">
          {link.url}
        </a>
        <CopyButton text={link.url} label={`Copy payment link for ${invoice.number}`} />
        {invoice.status !== "paid" && (
          <button
            type="button"
            className="text-[13px] font-bold text-muted hover:underline"
            onClick={async () => {
              try {
                const out = await runtime.removePaymentLink(account, invoice.number);
                onChanged(out.invoice, out.warning ?? `Payment link removed from ${invoice.number}.`);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Remove link
          </button>
        )}
      </p>
      {link.provider === "paypalme" && (
        <p className="mt-1 text-[13px] text-muted">PayPal.me payments are not found automatically: record them when they arrive.</p>
      )}
      {error && <RuntimeErrorNote message={error} title="Could not remove the link" />}
    </div>
  );
}

/** "Add payment link": pick one of the user's connected accounts; the runtime makes the link for what is owed. */
export function PaymentLinkDialog({
  account, invoice, onClose, onDone,
}: { account: AccountInfo; invoice: RtInvoice; onClose: () => void; onDone: (inv: RtInvoice, message: string) => void }) {
  const [rows, setRows] = useState<RtProviderStatus[] | null>(null);
  const [choice, setChoice] = useState<RtPayProvider | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<{ invoice: RtInvoice; warning: string | null } | null>(null);
  const id = `paylink-${invoice.number}`;
  const amount = linkAmount(invoice);

  useEffect(() => {
    runtime
      .payProviders(account)
      .then((got) => {
        setRows(got);
        const usable = got.filter((r) => r.available && r.connected);
        if (usable.length) setChoice(usable[0].provider);
      })
      .catch((e: Error) => setError(e.message));
  }, [account]);

  const usable = (rows ?? []).filter((r) => r.available && r.connected);
  const link = made?.invoice.payment_link;

  return (
    <Modal id={id} title={`Payment link for ${invoice.number}`} onClose={onClose}>
      {!made && (
        <>
          <p className="mt-2 text-sm text-muted">
            A link for <span className="font-bold text-ink">{money(amount)}</span>
            {invoice.status === "draft" ? ", the invoice total" : ", what is still owed"}. It goes on the PDF and in the email
            {invoice.payment_link ? "; the old link is switched off first" : ""}.
          </p>
          {rows && usable.length === 0 && (
            <p className="mt-3 rounded-xl bg-ground p-3 text-sm">
              No payment account is connected yet.{" "}
              <Link href="/settings#settings-payments" className="font-bold text-teal-dark underline">
                Connect one in Settings › Online payments
              </Link>
              .
            </p>
          )}
          {usable.length > 0 && (
            <fieldset className="mt-3 space-y-2">
              <legend className={fieldLabel}>Paid into</legend>
              {usable.map((r) => (
                <label key={r.provider} className="flex items-center gap-2 rounded-xl border border-border p-3 text-[15px]">
                  <input type="radio" name={`${id}-provider`} checked={choice === r.provider} onChange={() => setChoice(r.provider)} />
                  <span className="font-bold">{r.label}</span>
                  <span className="text-sm text-muted">{r.account}</span>
                  {r.test_mode && <TestModeBadge />}
                </label>
              ))}
            </fieldset>
          )}
          {error && <div className="mt-3"><RuntimeErrorNote message={error} title="Could not make the link" /></div>}
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button type="button" className={secondaryButton} onClick={onClose}>Cancel</button>
            <button
              type="button"
              className={primaryButton}
              disabled={!choice || busy || amount <= 0}
              onClick={async () => {
                if (!choice) return;
                setBusy(true);
                setError(null);
                try {
                  setMade(await runtime.addPaymentLink(account, invoice.number, choice));
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Making the link…" : "Make payment link"}
            </button>
          </div>
        </>
      )}
      {made && link && (
        <>
          <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-bold">{LABEL[link.provider]} link for {money(link.amount_pence)}</span>
            {link.test_mode && <TestModeBadge />}
          </p>
          <label className={fieldLabel} htmlFor={`${id}-url`}>Payment link</label>
          <input id={`${id}-url`} readOnly className={fieldInput} value={link.url} onFocus={(e) => e.currentTarget.select()} />
          <div className="mt-2"><CopyButton text={link.url} label={`Copy payment link for ${invoice.number}`} /></div>
          {made.warning && <p className="mt-2 text-sm font-bold text-warn-ink">{made.warning}</p>}
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              className={primaryButton}
              onClick={() => onDone(made.invoice, `Payment link added to ${invoice.number}.`)}
            >
              Done
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

/** Payments found through the links when Invoices opened: each waits for the user's yes. */
export function OnlineFound({
  account, found, onApproved,
}: { account: AccountInfo; found: RtFoundPayment[]; onApproved: (inv: RtInvoice, message: string) => void }) {
  if (!found.length) return null;
  return (
    <section aria-label="Paid online" className="space-y-2 rounded-2xl border-2 border-teal bg-teal-tint/40 p-4">
      <h2 className="text-lg font-extrabold">Paid online: waiting for your approval</h2>
      <p className="text-sm text-muted">
        Found in your Stripe or PayPal account. Nothing is in your books until you approve; the fee goes in as its own
        expense (bank charges, VAT exempt).
      </p>
      <ul className="space-y-2">
        {found.map((f) => (
          <FoundRow key={f.payment_id} account={account} f={f} onApproved={onApproved} />
        ))}
      </ul>
    </section>
  );
}

function FoundRow({
  account, f, onApproved,
}: { account: AccountInfo; f: RtFoundPayment; onApproved: (inv: RtInvoice, message: string) => void }) {
  const [fee, setFee] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const typed = f.fee_pence === null ? parsePounds(fee) : null;
  return (
    <li className="rounded-xl border border-border bg-white p-3">
      <p className="flex flex-wrap items-center gap-2 text-[15px] font-bold">
        {f.invoice} · {f.customer} · {money(f.gross_pence)} via {LABEL[f.provider]} on {ukDate(f.date)}
        {f.test_mode && <TestModeBadge />}
      </p>
      <p className="text-sm text-muted">
        {f.fee_pence !== null ? (
          <>Fee {money(f.fee_pence)} · you receive {money(f.net_pence ?? 0)}</>
        ) : (
          <>{LABEL[f.provider]} has not said its fee yet: type it from your statement, or approve later.</>
        )}
        {f.gross_pence > f.balance_pence && <> · more than the {money(f.balance_pence)} owed: the rest is kept as a credit</>}
      </p>
      <table className="mt-2 w-full text-[13px] tabular-nums">
        <caption className="sr-only">What approving posts</caption>
        <tbody>
          {f.journal.map((j, n) => (
            <tr key={n}>
              <td className="py-0.5">{j.account}{j.vat_code ? ` (VAT ${j.vat_code})` : ""}</td>
              <td className="text-right">{j.debit_pence ? `Dr ${money(j.debit_pence)}` : ""}</td>
              <td className="text-right">{j.credit_pence ? `Cr ${money(j.credit_pence)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {f.fee_pence === null && (
          <div>
            <label className={fieldLabel} htmlFor={`fee-${f.payment_id}`}>Fee (£)</label>
            <input id={`fee-${f.payment_id}`} className={fieldInput} inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} />
          </div>
        )}
        <button
          type="button"
          className={primaryButton}
          disabled={busy || (f.fee_pence === null && typed === null)}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              const out = await runtime.approveOnlinePayment(account, f.invoice, {
                payment_id: f.payment_id,
                ...(f.fee_pence === null && typed !== null ? { fee_pence: typed } : {}),
              });
              onApproved(out.invoice, `${money(f.gross_pence)} from ${LABEL[f.provider]} recorded on ${f.invoice}.`);
            } catch (e) {
              setError((e as Error).message);
              setBusy(false);
            }
          }}
        >
          Approve {money(f.gross_pence)} on {f.invoice}
        </button>
      </div>
      {error && <RuntimeErrorNote message={error} title="Could not record it" />}
    </li>
  );
}
