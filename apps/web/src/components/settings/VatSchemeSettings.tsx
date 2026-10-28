"use client";

import { useEffect, useState } from "react";
import { useAccount, errorText, todayIso } from "@/components/jobs/useAccount";
import {
  runtime,
  type RtSchemeEntry,
  type RtSchemeName,
  type RtVatSchemeSettings,
  type RtVatSchemes,
} from "@/lib/runtime";

const input = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] font-normal text-ink";
const label = "text-[13px] font-bold text-ink";
const uk = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};

const SCHEMES: { value: RtSchemeName; label: string; hint: string }[] = [
  { value: "standard", label: "Standard", hint: "VAT on invoices you issue and receive" },
  { value: "cash", label: "Cash accounting", hint: "VAT when you are paid and when you pay (Notice 731)" },
  { value: "flat_rate", label: "Flat rate", hint: "A fixed % of your VAT-inclusive turnover (Notice 733)" },
];

const SOURCE_LABELS: Record<string, string> = {
  flat_rate: "Flat Rate Scheme (VAT Notice 733)",
  flat_rates: "Flat rates by type of business",
  cash: "Cash Accounting Scheme (VAT Notice 731)",
  annual: "Annual Accounting Scheme (VAT Notice 732)",
  boxes: "Filling in the VAT Return under each scheme (VAT Notice 700/12)",
};

function firstOfMonth(): string {
  return `${todayIso().slice(0, 7)}-01`;
}

/** Settings › Business › VAT scheme: flat rate, cash accounting and annual accounting, saved in the user's own books
 *  (_System/vat/schemes.json). The VAT page, reports and Ask then work the boxes out under the scheme by code. */
export default function VatSchemeSettings({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [view, setView] = useState<RtVatSchemes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  // The change being made: a scheme from a date.
  const [scheme, setScheme] = useState<RtSchemeName>("standard");
  const [from, setFrom] = useState(firstOfMonth);
  const [sector, setSector] = useState("");
  const [method, setMethod] = useState<"basic" | "cash">("basic");
  const [limited, setLimited] = useState<"auto" | "yes" | "no">("auto");
  const [cashExit, setCashExit] = useState<"immediate" | "six_months">("immediate");
  const [registered, setRegistered] = useState("");
  const [annualOn, setAnnualOn] = useState(false);
  const [annualStart, setAnnualStart] = useState(firstOfMonth);
  const [instalments, setInstalments] = useState<"monthly" | "quarterly">("monthly");
  const [basis, setBasis] = useState("");

  function show(v: RtVatSchemes) {
    setView(v);
    setRegistered(v.settings.registered_on ?? "");
    setAnnualOn(!!v.settings.annual);
    if (v.settings.annual) {
      setAnnualStart(v.settings.annual.start);
      setInstalments(v.settings.annual.instalments);
      setBasis(v.settings.annual.basis_pence != null ? String(v.settings.annual.basis_pence / 100) : "");
    }
    const now = v.current;
    setScheme(now.scheme);
    const entry = v.settings.schemes.find((e) => e.from === now.since);
    if (entry?.flat_rate) {
      setSector(entry.flat_rate.sector);
      setMethod(entry.flat_rate.turnover_method);
      setLimited(entry.flat_rate.limited_cost);
    }
  }

  useEffect(() => {
    if (!account) return;
    let stale = false;
    runtime.vatSchemes(account).then(
      (v) => !stale && show(v),
      (e) => !stale && setError(errorText(e)),
    );
    return () => {
      stale = true;
    };
  }, [account]);

  async function save(next: RtVatSchemeSettings) {
    if (!account) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      show(await runtime.saveVatSchemes(account, next));
      setSaved(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  function settingsWith(timeline: RtSchemeEntry[], capital?: string[]): RtVatSchemeSettings {
    const s = view!.settings;
    const pounds = Number(basis);
    return {
      registered_on: registered || null,
      schemes: timeline,
      annual: annualOn
        ? {
            start: annualStart,
            first_year_end: s.annual?.first_year_end ?? null,
            instalments,
            basis_pence: basis.trim() && Number.isFinite(pounds) && pounds >= 0 ? Math.round(pounds * 100) : null,
            end: s.annual?.end ?? null,
          }
        : null,
      capital_purchases: capital ?? s.capital_purchases,
      relevant_goods_accounts: s.relevant_goods_accounts ?? null,
      estimates: s.estimates ?? {},
    };
  }

  function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!view) return;
    if (scheme === "flat_rate" && !sector) return setError("Choose your type of business for the flat rate.");
    // Keep what was in use before `from`; the new scheme runs from `from` on.
    const before = view.settings.schemes
      .filter((x) => x.from < from)
      .map((x, i, all) => (i === all.length - 1 && x.scheme === "cash" && scheme !== "cash" ? { ...x, cash_exit: cashExit } : x));
    const last = before[before.length - 1];
    const same = last && last.scheme === scheme && scheme !== "flat_rate";
    const entry: RtSchemeEntry = {
      from,
      scheme,
      ...(scheme === "flat_rate" ? { flat_rate: { sector, turnover_method: method, limited_cost: limited } } : {}),
    };
    save(settingsWith(same ? before : [...before, entry]));
  }

  function remove(at: string) {
    if (!view) return;
    save(settingsWith(view.settings.schemes.filter((x) => x.from !== at)));
  }

  function toggleCapital(id: string, on: boolean) {
    if (!view) return;
    const now = new Set(view.settings.capital_purchases);
    if (on) now.add(id);
    else now.delete(id);
    save(settingsWith(view.settings.schemes, [...now]));
  }

  const leavingCash = view?.current.scheme === "cash" && scheme !== "cash";
  const flatInUse = view?.settings.schemes.some((x) => x.scheme === "flat_rate");

  return (
    <section id="settings-vat-scheme" aria-labelledby="settings-vat-scheme-title" className={`${card} scroll-mt-4`}>
      <h2 id="settings-vat-scheme-title" className={heading}>
        VAT scheme
      </h2>
      <p className="mt-1 text-sm text-muted">
        Flat rate, cash accounting or annual accounting. Saved in your own books, so the VAT page, reports and Ask work
        your boxes out under it, by code.
      </p>
      {account === null && <p className="mt-3 text-sm text-muted">Sign in to set your VAT scheme.</p>}
      {account && !view && !error && <p className="mt-3 text-sm text-muted">Loading your VAT scheme…</p>}
      {view && (
        <>
          <p className="mt-3 rounded-xl bg-ground p-3 text-[15px]" data-testid="vat-scheme-current">
            In use today: <strong>{view.current.label}</strong>
            {view.current.flat_rate_percent ? ` at ${view.current.flat_rate_percent}%` : ""}
            {view.current.since ? `, since ${uk(view.current.since)}` : ""}
            {view.current.annual && view.current.annual_period
              ? `; annual accounting for ${uk(view.current.annual_period[0])} – ${uk(view.current.annual_period[1])}`
              : ""}
            .
            {view.current.first_year_until && (
              <span className="block text-sm text-muted">
                First year of VAT registration: 1% off the flat rate up to {uk(view.current.first_year_until)}.
              </span>
            )}
            {view.current.scheme === "flat_rate" && (
              <span className="block text-sm text-muted">
                Each period Accnomos checks the limited cost test: if you spend under 2% of turnover (or under £1,000 a
                year) on goods, the rate is {view.current.limited_cost_rate}%.
              </span>
            )}
          </p>

          {view.settings.schemes.length > 0 && (
            <ul className="mt-3 divide-y divide-border rounded-xl border border-border" aria-label="Your VAT schemes">
              {view.settings.schemes.map((x) => (
                <li key={x.from} className="flex items-center justify-between gap-2 p-3 text-[15px]">
                  <span>
                    From {uk(x.from)}: {SCHEMES.find((s) => s.value === x.scheme)?.label}
                    {x.flat_rate ? ` · ${x.flat_rate.sector}` : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => remove(x.from)}
                    disabled={saving}
                    className="min-h-11 rounded-xl px-3 text-sm font-bold text-teal-dark underline underline-offset-2"
                    aria-label={`Remove the scheme from ${uk(x.from)}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          <form onSubmit={onSave} className="mt-3 space-y-3" aria-label="Change VAT scheme">
            <fieldset>
              <legend className={label}>Scheme</legend>
              <div className="mt-1 grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="VAT scheme">
                {SCHEMES.map((s) => (
                  <button
                    key={s.value}
                    type="button"
                    role="radio"
                    aria-checked={scheme === s.value}
                    onClick={() => setScheme(s.value)}
                    className={`min-h-11 rounded-xl border px-3 py-2 text-left text-[15px] font-bold ${
                      scheme === s.value ? "border-2 border-teal bg-teal-tint text-teal-dark" : "border-border text-ink"
                    }`}
                  >
                    {s.label}
                    <span className="block text-xs font-normal text-muted">{s.hint}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <label className={`${label} block`}>
              From
              <input
                type="date"
                required
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                aria-describedby="vat-scheme-from-hint"
                className={input}
              />
            </label>
            <p id="vat-scheme-from-hint" className="-mt-2 text-xs text-muted">
              Replaces anything saved from this date on.
            </p>
            {scheme === "cash" && (
              <p className="text-sm text-muted">
                Cash accounting starts on the first day of a VAT period, needs taxable turnover of £1.35 million or less,
                and cannot be backdated. Invoices from before it started stay on their invoice dates.
              </p>
            )}
            {leavingCash && (
              <label className={`${label} block`}>
                VAT on invoices and bills still unpaid when you leave cash accounting
                <select value={cashExit} onChange={(e) => setCashExit(e.target.value as typeof cashExit)} className={input}>
                  <option value="immediate">Account for it all in the last period on the scheme</option>
                  <option value="six_months">Account for it as it is paid over the next 6 months (Notice 731 §6.4)</option>
                </select>
              </label>
            )}
            {scheme === "flat_rate" && (
              <>
                <label className={`${label} block`}>
                  Type of business
                  <select value={sector} onChange={(e) => setSector(e.target.value)} className={input} required>
                    <option value="">Choose…</option>
                    {view.sectors.map((s) => (
                      <option key={s.name} value={s.name}>
                        {s.name} ({s.percent}%)
                      </option>
                    ))}
                  </select>
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className={`${label} block`}>
                    Turnover method
                    <select value={method} onChange={(e) => setMethod(e.target.value as typeof method)} className={input}>
                      <option value="basic">Basic: by invoice date</option>
                      <option value="cash">Cash based: when you are paid</option>
                    </select>
                  </label>
                  <label className={`${label} block`}>
                    Limited cost business (16.5%)
                    <select value={limited} onChange={(e) => setLimited(e.target.value as typeof limited)} className={input}>
                      <option value="auto">Test each period from my books</option>
                      <option value="yes">Always: I am a limited cost business</option>
                      <option value="no">Never: I am not</option>
                    </select>
                  </label>
                </div>
                <label className={`${label} block`}>
                  Date you registered for VAT (for the first-year 1% off)
                  <input type="date" value={registered} onChange={(e) => setRegistered(e.target.value)} className={input} />
                </label>
              </>
            )}
            <fieldset className="rounded-xl border border-border p-3">
              <legend className={`${label} px-1`}>Annual accounting</legend>
              <label className="flex min-h-11 items-center gap-3 text-[15px] font-bold text-ink">
                <input
                  type="checkbox"
                  checked={annualOn}
                  onChange={(e) => setAnnualOn(e.target.checked)}
                  className="h-5 w-5 accent-teal"
                />
                One VAT return a year, with interim payments (Notice 732)
              </label>
              {annualOn && (
                <div className="mt-2 grid gap-3 sm:grid-cols-3">
                  <label className={`${label} block`}>
                    First annual period starts
                    <input type="date" value={annualStart} onChange={(e) => setAnnualStart(e.target.value)} className={input} />
                  </label>
                  <label className={`${label} block`}>
                    Instalments
                    <select value={instalments} onChange={(e) => setInstalments(e.target.value as typeof instalments)} className={input}>
                      <option value="monthly">9 monthly (10% each)</option>
                      <option value="quarterly">3 quarterly (25% each)</option>
                    </select>
                  </label>
                  <label className={`${label} block`}>
                    Figure in HMRC&apos;s letter (£)
                    <input
                      inputMode="decimal"
                      value={basis}
                      onChange={(e) => setBasis(e.target.value)}
                      placeholder="e.g. 10000"
                      className={input}
                    />
                  </label>
                </div>
              )}
            </fieldset>
            <button
              type="submit"
              disabled={saving}
              className="h-11 rounded-xl bg-teal px-4 text-[15px] font-bold text-white disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save VAT scheme"}
            </button>
          </form>

          {flatInUse && view.capital_candidates.length > 0 && (
            <fieldset className="mt-4">
              <legend className={label}>Capital goods of £2,000 or more (VAT claimed outside the flat rate)</legend>
              <ul className="mt-1 space-y-1">
                {view.capital_candidates.map((c) => (
                  <li key={c.event_id}>
                    <label className="flex min-h-11 items-center gap-3 text-[15px]">
                      <input
                        type="checkbox"
                        checked={c.marked}
                        disabled={saving}
                        onChange={(e) => toggleCapital(c.event_id, e.target.checked)}
                        className="h-5 w-5 accent-teal"
                      />
                      {uk(c.date)} · {c.counterparty ?? "Purchase"} · £{c.gross} (VAT £{c.vat})
                    </label>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted">
                Tick only a single purchase of goods you will keep and use (a van, a computer), not services, stock or
                anything you will hire out (Notice 733 §15).
              </p>
            </fieldset>
          )}

          {view.checks.length > 0 && (
            <ul className="mt-4 space-y-2" aria-label="Scheme checks">
              {view.checks.map((c, i) => (
                <li
                  key={i}
                  className={`rounded-xl border p-3 text-sm ${
                    c.status === "ok" ? "border-border text-ink" : "border-warn-border bg-warn-bg text-warn-ink"
                  }`}
                >
                  <strong>{c.status === "ok" ? "OK" : c.status === "warn" ? "Check" : "Must leave"}:</strong> {c.message}{" "}
                  <a href={c.source} className="font-bold underline underline-offset-2" target="_blank" rel="noreferrer">
                    HMRC rule
                  </a>
                </li>
              ))}
            </ul>
          )}
          {view.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-warn-ink" aria-label="Worth a second look">
              {view.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <details className="mt-3 text-sm text-muted">
            <summary className="cursor-pointer font-bold">HMRC&apos;s rules (checked {view.checked})</summary>
            <ul className="mt-1 list-disc pl-5">
              {Object.entries(view.sources).map(([k, url]) => (
                <li key={k}>
                  <a href={url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                    {SOURCE_LABELS[k] ?? k}
                  </a>
                </li>
              ))}
            </ul>
            <p className="mt-1">Saved in {view.path}. Accnomos does not work out stock adjustments when you leave the flat rate.</p>
          </details>
        </>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-sm text-warn-ink">
          {error}
        </p>
      )}
      {saved && !error && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          Saved in your books.
        </p>
      )}
    </section>
  );
}
