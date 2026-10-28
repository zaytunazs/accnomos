"use client";

import { isDemo } from "@/lib/demo";
import { useEffect, useId, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import {
  lookupStatus,
  runtime,
  ukDate,
  vatCheckSourceLabel,
  type RtCompanyMatch,
  type RtLookupStatus,
  type RtVatCheck,
} from "@/lib/runtime";
import { parseRuntimeError } from "@/components/States";

/**
 * Official look-ups (services/runtime/app/company_lookup.py). AI proposes, user approves: a Companies House match
 * only fills the form, and a VAT check only reports what HMRC says. Neither saves or blocks anything.
 */

const input = "h-10 w-full rounded-xl border border-border bg-white px-3 text-[15px] focus:border-teal focus:outline-none";
const secondary =
  "shrink-0 rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted";

let statusOnce: Promise<RtLookupStatus | null> | null = null;

/** Which look-ups this runtime offers; null until known (and when it can't say: then both stay hidden). */
export function useLookupStatus(): RtLookupStatus | null {
  const [status, setStatus] = useState<RtLookupStatus | null>(null);
  useEffect(() => {
    let live = true;
    // The demo sandbox makes no Companies House or HMRC calls (the runtime refuses them): no look-ups offered.
    statusOnce ??= isDemo() ? Promise.resolve({ companies_house: false, vat_check: false, sample: false }) : lookupStatus();
    void statusOnce.then((s) => live && setStatus(s));
    return () => {
      live = false;
    };
  }, []);
  return status;
}

const errorText = (e: unknown) => (e as Error).message.replace(/ \(status \d+[^)]*\)$/, "");

/** "Look up" on Contacts › Edit: search Companies House by name or number, then pick a match to fill the form. */
export function CompanyLookup({ account, initialQuery, onPick }: {
  account: AccountInfo;
  initialQuery: string;
  onPick: (m: RtCompanyMatch) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState(initialQuery);
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<RtCompanyMatch[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function search() {
    if (q.trim().length < 2) return setErr("Type at least 2 characters of the name, or the company number.");
    setBusy(true);
    setErr(null);
    try {
      setItems((await runtime.lookupCompanies(account, q.trim())).items);
    } catch (e) {
      setItems(null);
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className={`${secondary} self-start`} onClick={() => setOpen(true)}>
        Look up on Companies House
      </button>
    );
  }
  return (
    <section aria-label="Look up on Companies House" className="flex flex-col gap-2 rounded-xl border border-border bg-ground p-3">
      <label htmlFor={`${id}-q`} className="text-[13px] font-bold text-muted">Company name or number</label>
      <div className="flex gap-2">
        <input
          id={`${id}-q`}
          className={input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault(); // inside the contact form: search, don't save
              void search();
            }
          }}
        />
        <button type="button" className={secondary} disabled={busy} onClick={() => void search()}>
          {busy ? "Looking…" : "Look up"}
        </button>
      </div>
      {err && <p role="alert" className="text-sm font-semibold text-warn-ink">{parseRuntimeError(err).detail || "The look-up did not answer — try again."}</p>}
      {items && (
        <div role="status" className="text-[13px] font-medium text-muted">
          {items.length === 0 ? "No companies found." : `${items.length} found. Pick one to fill the name, company number and address; nothing is saved until you press Save.`}
        </div>
      )}
      {items && items.length > 0 && (
        <ul aria-label="Companies House matches" className="flex flex-col gap-1">
          {items.map((m) => (
            <li key={m.company_number}>
              <button
                type="button"
                onClick={() => {
                  onPick(m);
                  setOpen(false);
                }}
                className="w-full rounded-lg border border-border bg-white px-3 py-2 text-left text-[14px] hover:border-teal"
              >
                <span className="font-bold">{m.name}</span>
                {m.sample && <span className="ml-2 rounded bg-warn-bg px-1.5 text-[12px] font-bold text-warn-ink">SAMPLE</span>}
                <span className="block text-[13px] text-muted">
                  {m.company_number}
                  {m.status ? ` · ${m.status}` : ""}
                  {m.address ? ` · ${m.address}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => setOpen(false)} className="self-start text-sm font-bold text-teal-dark hover:underline">
        Close look-up
      </button>
    </section>
  );
}

/** The result line: who HMRC says the number is registered to, always with where the answer came from. */
export function vatCheckText(c: RtVatCheck): string {
  const src = vatCheckSourceLabel(c.source);
  if (!c.registered) return `Not VAT-registered: HMRC has no business with ${c.vrn} (${src})`;
  const who = [c.name, c.address].filter(Boolean).join(", ");
  return `Registered to ${who || "a business HMRC didn't name"} (${src})`;
}

/**
 * "Check VAT number": asks HMRC (through the relay) only when tapped, then keeps the answer on the contact with
 * that number, so the next tap shows it without asking again. A name that differs is a warning, never a block.
 */
export function VatCheckButton({ account, vrn, name, contactId, initial, onChecked }: {
  account: AccountInfo;
  vrn: string;
  name: string;
  contactId?: string | null;
  initial?: RtVatCheck | null;
  onChecked?: () => void;
}) {
  const [check, setCheck] = useState<RtVatCheck | null>(initial && initial.vrn === vrn.replace(/\s+/g, "").toUpperCase() ? initial : null);
  const [differs, setDiffers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const r = await runtime.vatCheck(account, { vrn, name, contact_id: contactId ?? null });
      setCheck(r.check);
      setDiffers(r.name_differs);
      if (!r.cached) onChecked?.();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <button type="button" className={`${secondary} self-start`} disabled={busy} onClick={() => void run()} aria-label={`Check VAT number ${vrn} with HMRC`}>
        {busy ? "Checking…" : "Check VAT number"}
      </button>
      {/* aria-live without role="status": cards and panels already have one status line each */}
      <div aria-live="polite" className="text-[13px]">
        {check && (
          <p className={check.registered ? "font-semibold text-ink" : "font-semibold text-warn-ink"}>
            {vatCheckText(check)}
            <span className="block font-medium text-muted">
              Checked {ukDate(check.checked_at.slice(0, 10))}
              {check.consultation_number ? ` · HMRC reference ${check.consultation_number}` : ""}
            </span>
          </p>
        )}
        {check?.registered && differs && (
          <p className="mt-1 rounded-lg border border-warn-border bg-warn-bg px-2 py-1 font-semibold text-warn-ink">
            HMRC&apos;s name differs from {name}. Check it&apos;s the same business before you rely on this VAT number.
          </p>
        )}
      </div>
      {err && <p role="alert" className="text-[13px] font-semibold text-warn-ink">{parseRuntimeError(err).detail || "The check did not answer — try again."}</p>}
    </div>
  );
}
