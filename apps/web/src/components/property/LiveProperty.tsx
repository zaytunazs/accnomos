"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { clientFacts, disconnect, finishConnect, loadTokens, startConnect, takeCallback } from "@/lib/hmrc";
import { gbp, ukDate } from "@/lib/runtime";
import {
  BUSINESS_ID_RE,
  NINO_RE,
  landlordOn,
  property,
  propertyHmrc,
  taxYearOf,
  type CategoryKey,
  type RtProperty,
  type RtPropertyCategory,
  type RtPropertyEntry,
  type RtPropertyIn,
  type RtPropertyMtd,
  type RtPropertySettings,
  type RtPropertySubmission,
  type RtPropertySummary,
} from "@/lib/property";

const pounds = (pence: number) => (pence < 0 ? `-${gbp(-pence / 100)}` : gbp(pence / 100));
const londonToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
/** "12.50" -> 1250; null when it is not a plain amount of pounds and pence. */
const toPence = (text: string): number | null => (/^\d{1,9}(\.\d{1,2})?$/.test(text.trim()) ? Math.round(Number(text) * 100) : null);
const percent = (bp: number) => `${(bp / 100).toLocaleString("en-GB", { maximumFractionDigits: 2 })}%`;

const input = "h-11 min-w-0 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold disabled:opacity-60";
const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const h2 = "text-[19px] font-extrabold text-ink";
const label = "flex flex-col gap-1 text-sm font-bold text-ink";

const USE_LABEL: Record<RtPropertyIn["use"], string> = {
  residential: "Residential let",
  commercial: "Commercial (shop, office)",
  rent_a_room: "Room in my own home (Rent a Room)",
};

const blankProperty = { name: "", postcode: "", use: "residential" as RtPropertyIn["use"], furnished: false, holiday_let: false, joint: "sole" as RtPropertyIn["joint"], other: "", myShare: "50", form17: false };

type Callback = ReturnType<typeof takeCallback>;

export default function LiveProperty() {
  // Take HMRC's OAuth fragment during the first render, before MSAL's redirect handling (useAccount) can see it.
  const [callback] = useState<Callback>(() => (typeof window === "undefined" ? null : takeCallback()));
  useEffect(() => {
    // The router restores the address it hydrated with; take the code out of the address bar again.
    if (callback && window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, [callback]);
  const account = useAccount();
  const [shown, setShown] = useState<boolean | null>(null);
  useEffect(() => {
    queueMicrotask(() => setShown(landlordOn()));
  }, []);

  if (shown === null || account === undefined) return <LoadingSkeleton lines={3} label="Loading Property…" />;
  if (!shown)
    return (
      <p className={`${card} text-[15px] leading-7 text-muted`}>
        Landlord mode is off. Turn on <strong>I let property (landlord mode)</strong> in{" "}
        <Link href="/settings#settings-landlord" className="font-bold text-teal-dark">
          Settings
        </Link>{" "}
        to use this page.
      </p>
    );
  if (!account)
    return (
      <p className={`${card} flex flex-wrap items-center gap-x-3 gap-y-2 text-[15px] leading-7 text-muted`}>
        <SignInCta />
        <span>to keep your rental records in your own OneDrive.</span>
      </p>
    );
  return <Signed account={account} callback={callback} />;
}

function Signed({ account, callback }: { account: AccountInfo; callback: Callback }) {
  const [taxYear, setTaxYear] = useState(taxYearOf(londonToday()));
  const [props, setProps] = useState<RtProperty[]>([]);
  const [cats, setCats] = useState<RtPropertyCategory[]>([]);
  const [summary, setSummary] = useState<RtPropertySummary | null>(null);
  const [entries, setEntries] = useState<RtPropertyEntry[]>([]);
  const [settings, setSettings] = useState<RtPropertySettings | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState(blankProperty);
  const [entry, setEntry] = useState({ property: "", category: "rents" as CategoryKey, amount: "", date: londonToday(), description: "", paid: "bank" as "bank" | "cash" | "owner", replacing: false });

  const load = useCallback(async () => {
    const [p, c, s, e, st] = await Promise.all([
      property.list(account),
      property.categories(account),
      property.summary(account, taxYear),
      property.entries(account, taxYear),
      property.settings(account),
    ]);
    setProps(p);
    setCats(c);
    setSummary(s);
    setEntries(e);
    setSettings(st);
    setEntry((x) => (x.property || !p[0] ? x : { ...x, property: p[0].id }));
  }, [account, taxYear]);

  function fail(e: unknown) {
    const msg = (e as Error).message ?? String(e);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote(msg);
  }

  useEffect(() => {
    queueMicrotask(() =>
      load()
        .then(() => setReady(true))
        .catch((e) => {
          fail(e);
          setReady(true);
        }),
    );
  }, [load]);

  async function act<T>(key: string, fn: () => Promise<T>, done: string | ((r: T) => string)): Promise<boolean> {
    setBusy(key);
    setError(null);
    try {
      const r = await fn();
      setNote(typeof done === "function" ? done(r) : done);
      await load();
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function addProperty() {
    if (!form.name.trim()) return setNote("Give the property a name, such as Flat 2 or 14 Mill Lane.");
    let owners = [{ name: "Me", share_bp: 10000, me: true }];
    if (form.joint !== "sole") {
      const mine = Number(form.myShare);
      if (!form.other.trim() || !(mine > 0 && mine < 100)) return setNote("A jointly owned property needs the other owner's name and your share (1 to 99%).");
      const myBp = Math.round(mine * 100);
      owners = [
        { name: "Me", share_bp: myBp, me: true },
        { name: form.other.trim(), share_bp: 10000 - myBp, me: false },
      ];
    }
    const body: RtPropertyIn = {
      name: form.name.trim(),
      postcode: form.postcode.trim() || null,
      use: form.use,
      furnished: form.furnished,
      holiday_let: form.holiday_let,
      joint: form.joint,
      form17: form.joint === "spouses" && form.form17,
      owners,
    };
    if (await act("property", () => property.add(account, body), `Added ${body.name}`)) setForm(blankProperty);
  }

  async function addEntry() {
    const pence = toPence(entry.amount);
    if (!entry.property) return setNote("Add a property first.");
    if (!pence) return setNote("The amount is in pounds, such as 850 or 72.40.");
    if (!entry.description.trim()) return setNote("Say what it was, such as 'October rent' or 'Boiler service'.");
    const body = {
      property_id: entry.property,
      date: entry.date,
      category: entry.category,
      amount_pence: pence,
      description: entry.description.trim(),
      paid_via: entry.paid,
      replacing_existing_item: entry.replacing,
    };
    const cat = cats.find((c) => c.key === entry.category);
    if (await act("entry", () => property.addEntry(account, body), `Recorded ${pounds(pence)}: ${cat?.label ?? entry.category}`))
      setEntry({ ...entry, amount: "", description: "", replacing: false });
  }

  if (!ready) return <LoadingSkeleton lines={4} label="Loading your property figures…" />;
  if (error) return <RuntimeErrorNote message={error} />;

  const nameOf = (id: string | null) => props.find((p) => p.id === id)?.name ?? "Not on a property";
  const incomeCats = cats.filter((c) => c.group === "income");
  const costCats = cats.filter((c) => c.group !== "income");
  const untagged = entries.filter((e) => !e.property_id);
  const years = [taxYearOf(londonToday()), "2025-26"].filter((y, i, a) => a.indexOf(y) === i);

  return (
    <div className="flex flex-col gap-5">
      {note && (
        <p role="status" className="rounded-xl bg-ground px-4 py-3 text-[15px] text-ink">
          {note}
        </p>
      )}

      <label className={`${label} max-w-xs`}>
        Tax year
        <select className={input} value={taxYear} onChange={(e) => setTaxYear(e.target.value)}>
          {years.map((y) => (
            <option key={y} value={y}>
              {y.replace("-", " to 20")}
            </option>
          ))}
        </select>
      </label>

      <section aria-labelledby="property-list" className={card}>
        <h2 id="property-list" className={h2}>
          Your properties
        </h2>
        {props.length === 0 ? (
          <p className="mt-2 text-[15px] text-muted">No properties yet. Add the one or two you let below.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {props.map((p) => (
              <li key={p.id} className="rounded-xl border border-border px-4 py-3 text-[15px]">
                <strong>{p.name}</strong>
                {p.postcode ? ` · ${p.postcode}` : ""} · {USE_LABEL[p.use]}
                {p.furnished ? " · furnished" : ""}
                <span className="block text-sm text-muted">
                  {p.joint === "sole"
                    ? "Owned by you alone"
                    : p.owners.map((o) => `${o.me ? "You" : o.name} ${percent(o.share_bp)}`).join(", ") +
                      (p.joint === "spouses" ? (p.form17 ? " (Form 17 declaration in force)" : " (spouses: taxed 50:50 without a Form 17)") : "")}
                </span>
              </li>
            ))}
          </ul>
        )}
        <details className="mt-4" open={props.length === 0}>
          <summary className="cursor-pointer text-[15px] font-bold text-teal-dark">Add a property</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className={label}>
              Name
              <input className={input} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className={label}>
              Postcode
              <input className={input} value={form.postcode} onChange={(e) => setForm({ ...form, postcode: e.target.value })} />
            </label>
            <label className={label}>
              How it is let
              <select className={input} value={form.use} onChange={(e) => setForm({ ...form, use: e.target.value as RtPropertyIn["use"] })}>
                {Object.entries(USE_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className={label}>
              Who owns it
              <select className={input} value={form.joint} onChange={(e) => setForm({ ...form, joint: e.target.value as RtPropertyIn["joint"] })}>
                <option value="sole">Just me</option>
                <option value="spouses">Me and my spouse or civil partner</option>
                <option value="other">Me and someone else</option>
              </select>
            </label>
            {form.joint !== "sole" && (
              <>
                <label className={label}>
                  Other owner&apos;s name
                  <input className={input} value={form.other} onChange={(e) => setForm({ ...form, other: e.target.value })} />
                </label>
                <label className={label}>
                  Your share (%)
                  <input className={input} inputMode="decimal" value={form.myShare} onChange={(e) => setForm({ ...form, myShare: e.target.value })} />
                </label>
              </>
            )}
          </div>
          <div className="mt-3 flex flex-col gap-2 text-[15px]">
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" className="h-5 w-5 accent-teal" checked={form.furnished} onChange={(e) => setForm({ ...form, furnished: e.target.checked })} />
              Furnished
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" className="h-5 w-5 accent-teal" checked={form.holiday_let} onChange={(e) => setForm({ ...form, holiday_let: e.target.checked })} />
              Holiday let (taxed as an ordinary residential let since 6 April 2025)
            </label>
            {form.joint === "spouses" && (
              <label className="flex min-h-11 items-center gap-3">
                <input type="checkbox" className="h-5 w-5 accent-teal" checked={form.form17} onChange={(e) => setForm({ ...form, form17: e.target.checked })} />
                We have sent HMRC a Form 17 declaration of our actual shares
              </label>
            )}
          </div>
          <button type="button" className={`${button} mt-3`} disabled={busy === "property"} onClick={addProperty}>
            Add property
          </button>
        </details>
      </section>

      {props.length > 0 && (
        <section aria-labelledby="property-record" className={card}>
          <h2 id="property-record" className={h2}>
            Record rent or a cost
          </h2>
          <p className="mt-1 text-sm text-muted">Posted to your books as your own approved entry. Kept off the VAT return.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className={label}>
              Property
              <select className={input} value={entry.property} onChange={(e) => setEntry({ ...entry, property: e.target.value })}>
                {props.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className={label}>
              What it is
              <select className={input} value={entry.category} onChange={(e) => setEntry({ ...entry, category: e.target.value as CategoryKey })}>
                <optgroup label="Money in">
                  {incomeCats.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Money out">
                  {costCats.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </optgroup>
              </select>
            </label>
            <label className={label}>
              Amount (£)
              <input className={input} inputMode="decimal" value={entry.amount} onChange={(e) => setEntry({ ...entry, amount: e.target.value })} />
            </label>
            <label className={label}>
              Date
              <input className={input} type="date" value={entry.date} onChange={(e) => setEntry({ ...entry, date: e.target.value })} />
            </label>
            <label className={label}>
              Description
              <input className={input} value={entry.description} onChange={(e) => setEntry({ ...entry, description: e.target.value })} />
            </label>
            <label className={label}>
              Paid through
              <select className={input} value={entry.paid} onChange={(e) => setEntry({ ...entry, paid: e.target.value as "bank" | "cash" | "owner" })}>
                <option value="bank">Bank account</option>
                <option value="cash">Cash</option>
                <option value="owner">My own money (owed back to me)</option>
              </select>
            </label>
          </div>
          {entry.category === "domestic_items" && (
            <label className="mt-3 flex min-h-11 items-center gap-3 text-[15px]">
              <input type="checkbox" className="h-5 w-5 accent-teal" checked={entry.replacing} onChange={(e) => setEntry({ ...entry, replacing: e.target.checked })} />
              It replaces an item that was already there (like for like)
            </label>
          )}
          {entry.category === "finance_res" && (
            <p className="mt-2 text-sm text-muted">Mortgage interest on a home you let is not an expense: it gives a tax reduction at the basic rate instead.</p>
          )}
          <button type="button" className={`${button} mt-3`} disabled={busy === "entry"} onClick={addEntry}>
            Record
          </button>
        </section>
      )}

      {summary && <YearSummary summary={summary} />}

      <section aria-labelledby="property-entries" className={card}>
        <h2 id="property-entries" className={h2}>
          Entries this tax year
        </h2>
        {entries.length === 0 ? (
          <p className="mt-2 text-[15px] text-muted">Nothing yet. A receipt you approve in Review can be put on a property here.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {entries.map((e) => (
              <li key={e.event_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-4 py-3 text-[15px]">
                <span>
                  <strong>{ukDate(e.date)}</strong> · {e.description ?? e.label}
                  <span className="block text-sm text-muted">
                    {nameOf(e.property_id)} · {e.label}
                    {e.undone ? " · undone" : ""}
                  </span>
                </span>
                <span className="font-bold">{e.side === "income" ? pounds(e.amount_pence) : `-${pounds(e.amount_pence)}`}</span>
              </li>
            ))}
          </ul>
        )}
        {untagged.length > 0 && props.length > 1 && (
          <p className="mt-3 text-sm text-muted">
            {untagged.length} {untagged.length === 1 ? "entry is" : "entries are"} not on a property yet:{" "}
            {untagged.map((e) => (
              <span key={e.event_id} className="mr-2 inline-flex items-center gap-2">
                <label className="sr-only" htmlFor={`tag-${e.event_id}`}>
                  Property for {e.description ?? e.label}
                </label>
                <select
                  id={`tag-${e.event_id}`}
                  className={input}
                  defaultValue=""
                  onChange={(ev) => ev.target.value && act(`tag-${e.event_id}`, () => property.tag(account, e.event_id, ev.target.value), "Entry put on the property")}
                >
                  <option value="">Choose…</option>
                  {props.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </span>
            ))}
          </p>
        )}
      </section>

      {settings && summary && summary.tax_year >= "2025-26" && (
        <MtdUpdate account={account} callback={callback} taxYear={taxYear} settings={settings} onSettings={async (s) => act("settings", () => property.saveSettings(account, s), "Landlord settings saved")} />
      )}
    </div>
  );
}

function Row({ name, value, strong }: { name: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border py-2 text-[15px] last:border-0">
      <dt className={strong ? "font-bold" : ""}>{name}</dt>
      <dd className={strong ? "font-bold" : ""}>{value}</dd>
    </div>
  );
}

function YearSummary({ summary }: { summary: RtPropertySummary }) {
  const m = summary.mine;
  return (
    <section aria-labelledby="property-year" className={card}>
      <h2 id="property-year" className={h2}>
        Your share for {summary.tax_year.replace("-", " to 20")}
      </h2>
      <p className="mt-1 text-sm text-muted">
        {ukDate(summary.start)} to {ukDate(summary.end)}. {summary.basis}
      </p>
      <dl className="mt-3">
        <Row name="Rents and other property income" value={pounds(m.income)} />
        <Row name="Allowable expenses" value={pounds(m.expenses)} />
        {m.domestic_items !== 0 && <Row name="Replacing domestic items" value={pounds(m.domestic_items)} />}
        {summary.rent_a_room_exempt > 0 && <Row name="Rent a Room exempt amount" value={pounds(summary.rent_a_room_exempt)} />}
        <Row name="Property profit" value={pounds(m.profit - summary.rent_a_room_exempt)} strong />
        <Row name="Mortgage interest and loan costs (residential)" value={pounds(m.finance_res)} />
        <Row name={`Estimated tax reduction (${summary.finance.rate_percent}%)`} value={pounds(summary.finance.credit)} strong />
        {summary.finance.carried_forward > 0 && <Row name="Finance costs to carry forward" value={pounds(summary.finance.carried_forward)} />}
      </dl>
      <p className="mt-2 text-sm text-muted">{summary.finance.note}</p>
      {summary.properties.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-[15px]">
            <caption className="sr-only">Each property, whole and your share</caption>
            <thead>
              <tr className="text-sm text-muted">
                <th scope="col" className="py-1 pr-3">Property</th>
                <th scope="col" className="py-1 pr-3">Income</th>
                <th scope="col" className="py-1 pr-3">Profit</th>
                <th scope="col" className="py-1 pr-3">Your share</th>
                <th scope="col" className="py-1">Your profit</th>
              </tr>
            </thead>
            <tbody>
              {summary.properties.map((p) => (
                <tr key={p.property_id} className="border-t border-border">
                  <th scope="row" className="py-2 pr-3 font-bold">{p.name}</th>
                  <td className="py-2 pr-3">{pounds(p.whole.income)}</td>
                  <td className="py-2 pr-3">{pounds(p.whole.profit)}</td>
                  <td className="py-2 pr-3">{percent(p.my_share_bp)}</td>
                  <td className="py-2">{pounds(p.mine.profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-sm text-muted">{summary.allowance.note}</p>
      {summary.warnings.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm text-ink">
          {summary.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MtdUpdate({
  account,
  callback,
  taxYear,
  settings,
  onSettings,
}: {
  account: AccountInfo;
  callback: Callback;
  taxYear: string;
  settings: RtPropertySettings;
  onSettings: (s: RtPropertySettings) => Promise<boolean>;
}) {
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  const [mtd, setMtd] = useState<RtPropertyMtd | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [nino, setNino] = useState("");
  const [businessId, setBusinessId] = useState(settings.business_id ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<RtPropertySubmission[]>([]);

  useEffect(() => {
    const cb = callback;
    (async () => {
      if (cb && "error" in cb) {
        disconnect("property");
        setNote(`HMRC sign-in didn't finish: ${cb.description || cb.error}`);
      } else if (cb) {
        await finishConnect(cb, "property").catch((e: Error) => setNote(e.message));
      }
      setConnected(Boolean(loadTokens("property")));
    })();
  }, [callback]);

  useEffect(() => {
    let stale = false;
    property.mtd(account, taxYear, periodEnd ?? undefined).then(
      (m) => {
        if (stale) return;
        setMtd(m);
        setConfirmed(false); // a tick is for the figures shown, not for new ones
      },
      (e: Error) => !stale && setNote(e.message),
    );
    property.submissions(account, taxYear).then((s) => !stale && setSent(s), () => !stale && setSent([]));
    return () => {
      stale = true;
    };
  }, [account, taxYear, periodEnd, settings]);

  async function exportFile() {
    if (!mtd) return;
    setBusy(true);
    try {
      const r = await property.exportFile(account, taxYear, mtd.period_end);
      setNote(`Saved ${r.name} in your OneDrive (07 Reports), ready to submit with your MTD software or agent.`);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function findBusiness() {
    const n = nino.replace(/\s+/g, "").toUpperCase();
    if (!NINO_RE.test(n)) return setNote("A National Insurance number looks like QQ123456C.");
    setBusy(true);
    try {
      const facts = await clientFacts(account.homeAccountId);
      const r = await propertyHmrc.businesses(n, facts);
      const uk = r.hmrc?.listOfBusinesses?.find((b) => b.typeOfBusiness === "uk-property");
      if (uk) {
        setBusinessId(uk.businessId);
        await onSettings({ ...settings, business_id: uk.businessId });
      } else setNote("HMRC lists no UK property business for this person. In the sandbox you can create a test one.");
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!mtd) return;
    const n = nino.replace(/\s+/g, "").toUpperCase();
    if (!NINO_RE.test(n) || !BUSINESS_ID_RE.test(businessId)) return setNote("Enter the National Insurance number and HMRC's business ID first.");
    setBusy(true);
    try {
      const facts = await clientFacts(account.homeAccountId);
      const r = await propertyHmrc.submitCumulative(n, businessId, taxYear, facts, mtd.cumulative);
      const rec = await property.recordSubmission(account, {
        tax_year: taxYear,
        kind: "cumulative",
        period_end: mtd.period_end,
        business_id: businessId,
        sent: mtd.cumulative,
        status: 204,
        correlation_id: r.correlation_id,
      });
      setNote(`Sent to HMRC's sandbox${r.correlation_id ? ` (reference ${r.correlation_id})` : ""}.${rec.matched_books ? "" : " Your books have changed since: check the figures."}`);
      setConfirmed(false);
      setSent(await property.submissions(account, taxYear));
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="property-mtd" className={card}>
      <h2 id="property-mtd" className={h2}>
        Quarterly update to HMRC
      </h2>
      <p className="mt-1 text-sm text-muted">
        Making Tax Digital for Income Tax: each update covers 6 April to the end of the quarter and replaces the one before. Accnomos makes the file to
        submit; sending it straight to HMRC works in HMRC&apos;s sandbox only.
      </p>
      {note && (
        <p role="status" className="mt-3 rounded-xl bg-ground px-4 py-3 text-[15px] text-ink">
          {note}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className={label}>
          Quarter ending
          <select className={input} value={periodEnd ?? mtd?.period_end ?? ""} onChange={(e) => setPeriodEnd(e.target.value)}>
            {(mtd?.quarter_ends ?? []).map((d) => (
              <option key={d} value={d}>
                {ukDate(d)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-h-11 items-center gap-3 text-[15px]">
          <input
            type="checkbox"
            className="h-5 w-5 accent-teal"
            checked={settings.consolidated_expenses}
            disabled={!mtd?.consolidated_allowed}
            onChange={(e) => onSettings({ ...settings, consolidated_expenses: e.target.checked })}
          />
          Send expenses as one total (income under £90,000)
        </label>
      </div>
      {mtd && (
        <>
          <dl className="mt-3">
            {mtd.sa105
              .filter((b) => b.pence !== 0)
              .map((b) => (
                <Row key={b.box} name={`Box ${b.box}: ${b.label}`} value={pounds(b.pence)} />
              ))}
          </dl>
          <details className="mt-3">
            <summary className="cursor-pointer text-sm font-bold text-teal-dark">What would be sent (Property Business API 6.0)</summary>
            <pre tabIndex={0} aria-label="Request body" className="mt-2 overflow-x-auto rounded-xl bg-ground p-3 text-xs">{JSON.stringify(mtd.cumulative, null, 2)}</pre>
          </details>
          <button type="button" className={`${button} mt-3`} disabled={busy} onClick={exportFile}>
            Save file ready to submit
          </button>
        </>
      )}

      <div className="mt-5 border-t border-border pt-4">
        <h3 className="text-[17px] font-extrabold text-ink">HMRC sandbox</h3>
        <p className="mt-1 text-sm text-muted">Test data only: nothing reaches your real tax account.</p>
        {!connected ? (
          <button type="button" className={`${quiet} mt-3`} onClick={() => startConnect("property").catch((e: Error) => setNote(e.message))}>
            Connect to HMRC (sandbox)
          </button>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className={label}>
                National Insurance number
                <input className={input} value={nino} onChange={(e) => setNino(e.target.value)} autoComplete="off" />
              </label>
              <button type="button" className={quiet} disabled={busy} onClick={findBusiness}>
                Find my property business
              </button>
              <label className={label}>
                HMRC business ID
                <input className={input} value={businessId} onChange={(e) => setBusinessId(e.target.value.trim().toUpperCase())} />
              </label>
            </div>
            <label className="flex min-h-11 items-center gap-3 text-[15px]">
              <input type="checkbox" className="h-5 w-5 accent-teal" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              I have checked these figures and want to send them to HMRC&apos;s sandbox
            </label>
            <div className="flex flex-wrap gap-3">
              <button type="button" className={button} disabled={busy || !confirmed || !mtd} onClick={submit}>
                Send update (sandbox)
              </button>
              <button
                type="button"
                className={quiet}
                onClick={() => {
                  disconnect("property");
                  setConnected(false);
                }}
              >
                Disconnect
              </button>
            </div>
          </div>
        )}
        {sent.length > 0 && (
          <ul aria-label="Updates sent" className="mt-3 flex flex-col gap-1 text-sm">
            {sent.map((s) => (
              <li key={s.at}>
                {ukDate(s.at.slice(0, 10))}: to {s.period_end ? ukDate(s.period_end) : "year end"}, HMRC answered {s.status}
                {s.matched_books === false ? " (books changed since)" : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
