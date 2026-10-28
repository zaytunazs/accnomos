"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import SignInCta from "@/components/SignInCta";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { runtime, type RtShoppingIn, type RtShoppingList, type RtShoppingLookup, type RtSpecField } from "@/lib/runtime";
import { money, perMeasure, ukDay } from "@/lib/spending";
import { LiveOfferRow, SearchBanner } from "./LivePrices";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-5";
const input = "h-11 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60";
const quiet = "h-10 rounded-xl border border-border bg-white px-3 text-[14px] font-bold hover:bg-ground disabled:opacity-60";

export type SpecValues = Record<string, string>;

/** The specs as fields, not free chat: width, length, colour, quantity. Shared with Ask's card. */
export function SpecFields({ fields, values, onChange }: { fields: RtSpecField[]; values: SpecValues; onChange: (v: SpecValues) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {fields.map((f) => (
        <label key={f.name} className="flex flex-col text-[13px] font-bold text-muted">
          {f.label}
          {f.unit ? ` (${f.unit})` : ""}
          {f.kind === "choice" ? (
            <select className={input} value={values[f.name] ?? "any"} onChange={(e) => onChange({ ...values, [f.name]: e.target.value })}>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={`${input} w-28`}
              inputMode="decimal"
              value={values[f.name] ?? ""}
              required={f.required}
              onChange={(e) => onChange({ ...values, [f.name]: e.target.value })}
            />
          )}
        </label>
      ))}
    </div>
  );
}

/** Fields -> the body for POST /shopping or /shopping/propose. */
export function specBody(text: string, values: SpecValues): RtShoppingIn {
  const num = (k: string) => (values[k]?.trim() ? values[k].trim() : null);
  const colour = values.colour && values.colour !== "any" ? values.colour : null;
  return {
    text,
    spec: { width_mm: num("width_mm"), length_m: num("length_m"), colour },
    quantity: num("quantity") ?? "1",
  };
}

/** /shopping: add what you need, pick from what you bought before, tick off when bought. */
export default function LiveShopping() {
  const account = useAccount();
  const [list, setList] = useState<RtShoppingList | null>(null);
  const [text, setText] = useState("");
  const [found, setFound] = useState<RtShoppingLookup | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [spec, setSpec] = useState<SpecValues>({ quantity: "1" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setList(await runtime.shopping(account));
      setError(null);
    } catch (e) {
      if ((e as Error).message !== "redirecting for consent") setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function lookUp() {
    if (!account || !text.trim()) return;
    setBusy("lookup");
    setError(null);
    try {
      const r = await runtime.shoppingLookup(account, text.trim());
      setFound(r);
      setPicked(r.options.length === 1 ? r.options[0].key : null);
      setSpec({ quantity: quantity || "1" });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function add() {
    if (!account || !found) return;
    const body: RtShoppingIn = found.options.length
      ? { text: found.text, option_key: picked, quantity: quantity || "1" }
      : specBody(found.text, spec);
    if (await act("add", () => runtime.addShopping(account, body))) {
      setFound(null);
      setText("");
      setQuantity("1");
    }
  }

  if (account === undefined) return <LoadingSkeleton lines={3} label="Loading your shopping list…" />;
  if (account === null)
    return (
      <div className={`${card} flex flex-col items-start gap-3`}>
        <p className="text-[15px] leading-7 text-muted">
          Once your OneDrive is connected, add what you need to buy. Accnomos finds it in your past receipts, asks which one
          you mean, and suggests the cheapest supplier you have used. The list lives in your OneDrive.
        </p>
        <SignInCta />
      </div>
    );

  const open = list?.items.filter((i) => !i.done) ?? [];
  const done = list?.items.filter((i) => i.done) ?? [];
  return (
    <div className="flex flex-col gap-4">
      {list && <SearchBanner status={list.web_search} />}
      {error && <RuntimeErrorNote message={error} />}
      <section aria-labelledby="shop-add" className={card}>
        <h2 id="shop-add" className="text-lg font-extrabold tracking-tight">
          Add an item
        </h2>
        <form
          aria-label="Add an item"
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void lookUp();
          }}
        >
          <label className="flex min-w-0 flex-1 flex-col text-[13px] font-bold text-muted">
            What do you need?
            <input className={`${input} min-w-0`} value={text} maxLength={120} placeholder="packing tape" onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="submit" className={button} disabled={busy !== null || !text.trim()} title={text.trim() ? undefined : "Type what you need first"}>
            {busy === "lookup" ? "Looking…" : "Look up"}
          </button>
        </form>
        {found && (
          <div className="mt-3 flex flex-col gap-3" aria-label="What I found">
            <p className="text-[15px] leading-7">{found.question_md}</p>
            {found.options.length > 0 ? (
              <fieldset className="flex flex-col gap-2">
                <legend className="sr-only">Which one?</legend>
                {found.options.map((o) => (
                  <label key={o.key} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-[14px] ${picked === o.key ? "border-teal bg-teal-tint" : "border-border"}`}>
                    <input type="radio" name="option" checked={picked === o.key} onChange={() => setPicked(o.key)} />
                    <span className="min-w-0">
                      <strong>{o.description}</strong>
                      <span className="block text-muted">
                        Last time {money(o.unit_price)} from {o.supplier}, {ukDay(o.date)} · {perMeasure(o.per_measure, o.measure_word)}
                      </span>
                      {o.cheapest && (
                        <span className="block text-teal-dark">
                          Cheapest in your books: {o.cheapest.supplier}, {perMeasure(o.cheapest.per_measure, o.cheapest.measure_word)}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
                <label className="flex flex-col text-[13px] font-bold text-muted">
                  Quantity
                  <input className={`${input} w-28`} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
                </label>
              </fieldset>
            ) : (
              <SpecFields fields={found.fields} values={spec} onChange={setSpec} />
            )}
            {found.live_offers.length > 0 && (
              <div>
                <p className="text-[12px] font-bold uppercase tracking-wide text-muted">Live offers (after your history)</p>
                <ul className="divide-y divide-border text-[14px]">
                  {found.live_offers.map((o) => (
                    <LiveOfferRow key={o.url} offer={o} />
                  ))}
                </ul>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={button}
                disabled={busy !== null || (found.options.length > 0 && !picked)}
                title={found.options.length > 0 && !picked ? "Pick one first" : undefined}
                onClick={() => void add()}
              >
                Add to list
              </button>
              <button type="button" className={quiet} onClick={() => setFound(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      <section aria-labelledby="shop-list" className={card}>
        <h2 id="shop-list" className="text-lg font-extrabold tracking-tight">
          To buy ({open.length})
        </h2>
        {!list ? (
          <LoadingSkeleton lines={2} label="Loading your shopping list…" />
        ) : open.length === 0 && done.length === 0 ? (
          <p className="mt-2 text-sm text-muted">Nothing on the list yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-border" aria-label="Shopping list">
            {[...open, ...done].map((i) => (
              <li key={i.id} className="flex items-start justify-between gap-3 py-2 text-[14px]">
                <label className="flex min-w-0 gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={i.done}
                    disabled={busy !== null}
                    onChange={(e) => {
                      const done = e.target.checked;
                      // Shown at once; the reload after the call puts it right if the runtime refused.
                      setList((l) => (l ? { ...l, items: l.items.map((x) => (x.id === i.id ? { ...x, done } : x)) } : l));
                      void act(`tick-${i.id}`, () => runtime.tickShopping(account, i.id, done));
                    }}
                  />
                  <span className={`min-w-0 ${i.done ? "text-muted line-through" : ""}`}>
                    <strong>
                      {i.quantity} × {i.description}
                    </strong>
                    <span className="block text-muted">
                      {i.suggested
                        ? `${i.suggested.supplier}, ${money(i.suggested.unit_price)} (${i.suggested.basis})`
                        : "No supplier in your books yet"}
                      {i.live_offer ? ` · live: ${i.live_offer.supplier} ${money(i.live_offer.unit_price)} (${i.live_offer.source})` : ""}
                    </span>
                  </span>
                </label>
                <button
                  type="button"
                  className="shrink-0 rounded-lg border border-border px-2 py-0.5 text-[12px] font-bold text-muted hover:bg-ground"
                  aria-label={`Remove ${i.description}`}
                  disabled={busy !== null}
                  onClick={() => void act(`rm-${i.id}`, () => runtime.removeShopping(account, i.id))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={quiet} disabled title={list?.future_steps.purchase_order ?? "Not in this version"}>
            Turn into a purchase order
          </button>
          <button type="button" className={quiet} disabled title={list?.future_steps.email_supplier ?? "Not in this version"}>
            Draft email to supplier
          </button>
        </div>
        <p className="mt-1 text-[12px] text-muted">Purchase orders and supplier emails are a later step; they are switched off in this version.</p>
      </section>
    </div>
  );
}
