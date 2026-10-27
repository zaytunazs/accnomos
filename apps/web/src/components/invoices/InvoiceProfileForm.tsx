"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fieldArea, fieldInput, fieldLabel, primaryButton } from "@/components/invoices/Modal";
import { loadBusiness } from "@/lib/business";
import { useMsAccount } from "@/lib/invoices";
import { runtime, type RtInvoiceProfile } from "@/lib/runtime";

const EMPTY: RtInvoiceProfile = {
  name: "", address: "", email: null, phone: null, vrn: null, company_number: null,
  bank: { account_name: "", sort_code: "", account_number: "", iban: null }, logo_path: null, terms_days: 30, footer_note: null,
};

/**
 * How the business appears on its invoices: _System/Invoicing/profile.json in the user's OneDrive (not this
 * device), so every device prints the same invoice. The logo is uploaded into _System/Invoicing as well.
 */
export default function InvoiceProfileForm({ card, heading }: { card: string; heading: string }) {
  const { account, ready } = useMsAccount();
  const [form, setForm] = useState<RtInvoiceProfile>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<"save" | "logo" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!account) return;
    runtime.invoiceProfile(account).then((p) => {
      const b = loadBusiness();
      // First time: start from the onboarding details on this device.
      setForm(p.name ? p : { ...p, name: b?.name ?? "", vrn: b?.vatNumber || null, email: b?.email || null });
      setLoaded(true);
    }).catch((e) => setError((e as Error).message));
  }, [account]);

  const set = <K extends keyof RtInvoiceProfile>(k: K, v: RtInvoiceProfile[K]) => setForm((f) => ({ ...f, [k]: v }));
  const setBank = (k: keyof RtInvoiceProfile["bank"], v: string) => setForm((f) => ({ ...f, bank: { ...f.bank, [k]: v } }));
  const detail = (e: unknown) => {
    const msg = (e as Error).message;
    return /"msg":"([^"]+)"/.exec(msg)?.[1] ?? /"detail":"([^"]+)"/.exec(msg)?.[1] ?? msg;
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!account) return;
    setBusy("save");
    setNote(null);
    setError(null);
    try {
      const blank = (s: string | null) => (s && s.trim()) || null;
      setForm(await runtime.saveInvoiceProfile(account, {
        ...form, email: blank(form.email), phone: blank(form.phone), vrn: blank(form.vrn), company_number: blank(form.company_number),
        footer_note: blank(form.footer_note), bank: { ...form.bank, iban: blank(form.bank.iban) },
      }));
      setNote("Saved in your OneDrive (_System/Invoicing/profile.json).");
    } catch (err) {
      setError(detail(err));
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File | undefined) {
    if (!account || !file) return;
    setBusy("logo");
    setError(null);
    try {
      const p = await runtime.uploadInvoiceLogo(account, file);
      set("logo_path", p.logo_path);
      setNote(`Logo saved as ${p.logo_path}.`);
    } catch (err) {
      setError(detail(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section id="invoice-profile" aria-labelledby="invoice-profile-title" className={card}>
      <h2 id="invoice-profile-title" className={heading}>On your invoices</h2>
      <p className="mt-1 text-sm text-muted">
        Your name, address, VAT number and bank details as they print on every invoice. Kept in your OneDrive, so
        every device prints the same.
      </p>
      {ready && !account && <p className="mt-3 text-sm text-muted">Sign in with Microsoft to set this up.</p>}
      {account && !loaded && !error && <p className="mt-3 text-sm text-muted">Loading…</p>}
      {account && loaded && (
        <form onSubmit={save} noValidate className="mt-3 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={fieldLabel} htmlFor="ip-name">Business name</label>
              <input id="ip-name" className={fieldInput} value={form.name} onChange={(e) => set("name", e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="ip-vrn">VAT registration number</label>
              <input id="ip-vrn" className={fieldInput} placeholder="GB 123 4567 89" value={form.vrn ?? ""} onChange={(e) => set("vrn", e.target.value)} />
              <p className="mt-1 text-xs text-muted">Leave blank if you are not VAT registered: invoices then cannot charge VAT.</p>
            </div>
            <div className="sm:col-span-2">
              <label className={fieldLabel} htmlFor="ip-address">Address</label>
              <textarea id="ip-address" rows={3} className={fieldArea} value={form.address} onChange={(e) => set("address", e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="ip-email">Email</label>
              <input id="ip-email" type="email" className={fieldInput} value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="ip-phone">Phone</label>
              <input id="ip-phone" className={fieldInput} value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="ip-company">Company number (optional)</label>
              <input id="ip-company" className={fieldInput} value={form.company_number ?? ""} onChange={(e) => set("company_number", e.target.value)} />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="ip-terms">Payment terms (days)</label>
              <input id="ip-terms" type="number" min={0} max={120} className={fieldInput} value={form.terms_days}
                onChange={(e) => set("terms_days", Math.max(0, Math.min(120, Number(e.target.value) || 0)))} />
            </div>
          </div>

          <fieldset className="rounded-xl border border-border p-3">
            <legend className={`${fieldLabel} px-1`}>Bank details for payment</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className={fieldLabel} htmlFor="ip-acname">Account name</label>
                <input id="ip-acname" className={fieldInput} value={form.bank.account_name} onChange={(e) => setBank("account_name", e.target.value)} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor="ip-sort">Sort code</label>
                <input id="ip-sort" inputMode="numeric" className={fieldInput} placeholder="12-34-56" value={form.bank.sort_code} onChange={(e) => setBank("sort_code", e.target.value)} />
              </div>
              <div>
                <label className={fieldLabel} htmlFor="ip-acno">Account number</label>
                <input id="ip-acno" inputMode="numeric" className={fieldInput} value={form.bank.account_number} onChange={(e) => setBank("account_number", e.target.value)} />
              </div>
            </div>
          </fieldset>

          <div>
            <label className={fieldLabel} htmlFor="ip-footer">Footer note (optional)</label>
            <input id="ip-footer" className={fieldInput} placeholder="Thank you for your business" value={form.footer_note ?? ""} onChange={(e) => set("footer_note", e.target.value)} />
          </div>

          <div>
            <label className={fieldLabel} htmlFor="ip-logo">Logo (PNG or JPEG, up to 1 MB)</label>
            <input id="ip-logo" type="file" accept="image/png,image/jpeg" disabled={busy !== null}
              onChange={(e) => upload(e.target.files?.[0])} className="mt-1 block w-full text-sm text-muted file:mr-3 file:h-10 file:rounded-xl file:border file:border-border file:bg-white file:px-4 file:font-bold" />
            <p className="mt-1 text-xs text-muted">{form.logo_path ? `In your folder as ${form.logo_path}` : "No logo yet"}</p>
          </div>

          <button type="submit" disabled={busy !== null} className={primaryButton}>{busy === "save" ? "Saving…" : "Save invoice details"}</button>
        </form>
      )}
      {note && <p role="status" className="mt-3 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <p role="alert" className="mt-3 text-sm font-bold text-warn-ink">{error}</p>}
    </section>
  );
}
