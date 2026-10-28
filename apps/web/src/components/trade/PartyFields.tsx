"use client";

import { fieldArea, fieldInput, fieldLabel } from "@/components/invoices/Modal";
import type { RtInvoiceCustomer } from "@/lib/runtime";

export const EMPTY_PARTY: RtInvoiceCustomer = { contact_id: null, name: "", email: null, address: null, vrn: null };

/** Who the document is to: pick from known contacts, or type a new one. */
export default function PartyFields({
  party, onChange, known, noun, idPrefix, emailLabel,
}: {
  party: RtInvoiceCustomer;
  onChange: (p: RtInvoiceCustomer) => void;
  known: RtInvoiceCustomer[];
  noun: "customer" | "supplier";
  idPrefix: string;
  emailLabel: string;
}) {
  const patch = (p: Partial<RtInvoiceCustomer>) => onChange({ ...party, ...p });
  return (
    <div>
      {known.length > 0 && (
        <div className="mb-3">
          <label className={fieldLabel} htmlFor={`${idPrefix}-known`}>Pick one of your {noun}s</label>
          <select
            id={`${idPrefix}-known`}
            className={fieldInput}
            value={party.contact_id ?? ""}
            onChange={(e) => {
              const c = known.find((x) => x.contact_id === e.target.value);
              onChange(c ? { ...c } : { ...EMPTY_PARTY });
            }}
          >
            <option value="">A new {noun}</option>
            {known.map((c) => <option key={c.contact_id ?? c.name} value={c.contact_id ?? ""}>{c.name}</option>)}
          </select>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor={`${idPrefix}-name`}>Name</label>
          <input id={`${idPrefix}-name`} className={fieldInput} value={party.name} onChange={(e) => patch({ name: e.target.value })} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor={`${idPrefix}-email`}>{emailLabel}</label>
          <input id={`${idPrefix}-email`} type="email" className={fieldInput} value={party.email ?? ""} onChange={(e) => patch({ email: e.target.value })} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor={`${idPrefix}-address`}>Address</label>
          <textarea id={`${idPrefix}-address`} rows={3} className={fieldArea} value={party.address ?? ""} onChange={(e) => patch({ address: e.target.value })} />
        </div>
        <div>
          <label className={fieldLabel} htmlFor={`${idPrefix}-vrn`}>Their VAT number (optional)</label>
          <input
            id={`${idPrefix}-vrn`} className={fieldInput} value={party.vrn ?? ""} onChange={(e) => patch({ vrn: e.target.value })}
            aria-describedby={noun === "supplier" ? `${idPrefix}-vrn-why` : undefined}
          />
          {noun === "supplier" && (
            <p id={`${idPrefix}-vrn-why`} className="mt-1 text-[13px] text-muted">
              Without it, a bill over £250 made from this order waits in Review as &ldquo;needs a look&rdquo;: VAT can&apos;t be reclaimed without the supplier&apos;s VAT number.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** The party as the runtime takes it: blanks become null. */
export function cleanParty(p: RtInvoiceCustomer): RtInvoiceCustomer {
  const c = (s: string | null) => (s && s.trim()) || null;
  return { ...p, name: p.name.trim(), email: c(p.email), address: c(p.address), vrn: c(p.vrn) };
}
