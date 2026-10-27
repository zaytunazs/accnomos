"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { EmptyState, LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError, parseRuntimeError } from "@/components/States";
import SignInCta from "@/components/SignInCta";
import { getMsal, msalConfigured } from "@/lib/msal";
import {
  gbp,
  runtime,
  ukDate,
  type RtMileageEntry,
  type RtMileageSummary,
  type RtVehicle,
  type RtVehicleKind,
} from "@/lib/runtime";

const KINDS: RtVehicleKind[] = ["car", "van", "motorcycle", "bicycle"];
const pounds = (pence: number) => gbp(pence / 100);
const miles = (n: number) => n.toLocaleString("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const londonToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "Europe/London" });
const errorText = (e: unknown) => {
  const m = (e as Error).message ?? String(e);
  const detail = /"detail":\s*"([^"]+)"/.exec(m);
  return detail ? detail[1] : m;
};

/** '2026-27' for any day from 6 April 2026 to 5 April 2027 (the runtime does the same in mileage.py). */
function taxYearOf(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const start = m > 4 || (m === 4 && d >= 6) ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}
function previousTaxYear(ty: string): string {
  const start = Number(ty.slice(0, 4)) - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

const input = "h-11 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold disabled:opacity-60";

export default function LiveVehicles() {
  const [state, setState] = useState<"checking" | "off" | "live">("checking");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const currentYear = taxYearOf(londonToday());
  const [taxYear, setTaxYear] = useState(currentYear);
  const [vehicles, setVehicles] = useState<RtVehicle[]>([]);
  const [entries, setEntries] = useState<RtMileageEntry[]>([]);
  const [summary, setSummary] = useState<RtMileageSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ text: string; review?: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const newVehicleRef = useRef<HTMLInputElement>(null);

  function fail(e: unknown) {
    // Sign-in and server trouble block the page; a refusal with a reason ("has journeys in the mileage log") is a note.
    const msg = errorText(e);
    if (isAuthError(msg) || isServerError(msg)) setError(msg);
    else setNote({ text: parseRuntimeError(msg).detail || msg });
  }
  const [newVehicle, setNewVehicle] = useState({ name: "", registration: "", kind: "car" as RtVehicleKind, owned_by: "personal" as "personal" | "business" });
  const [trip, setTrip] = useState({ vehicle_id: "", date: londonToday(), from: "", to: "", miles: "", purpose: "" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTrip, setEditTrip] = useState({ vehicle_id: "", date: "", from: "", to: "", miles: "", purpose: "" });
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [rename, setRename] = useState({ name: "", registration: "" });

  const load = useCallback(async (acct: AccountInfo, ty: string) => {
    const [vs, es, s] = await Promise.all([runtime.vehicles(acct), runtime.mileage(acct, ty), runtime.mileageSummary(acct, ty)]);
    setVehicles(vs);
    setEntries(es);
    setSummary(s);
    setTrip((t) => (t.vehicle_id || !vs.some((v) => v.active) ? t : { ...t, vehicle_id: vs.find((v) => v.active)!.id }));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("off");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("off");
        setAccount(acct);
        await load(acct, currentYear);
        setState("live");
      } catch (e) {
        fail(e);
        setState("off");
      }
    })();
  }, [load, currentYear]);

  /** Run `fn`, then reload tax year `ty` (default: the one shown). True when it worked. */
  async function act(key: string, fn: () => Promise<unknown>, done?: string, ty: string = taxYear): Promise<boolean> {
    if (!account) return false;
    setBusy(key);
    setError(null);
    try {
      await fn();
      if (done) setNote({ text: done });
      setTaxYear(ty);
      await load(account, ty);
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function claim(period: string) {
    if (!account) return;
    setBusy(`claim-${period}`);
    try {
      const r = await runtime.proposeAllowance(account, taxYear, period);
      const amount = gbp(r.proposal.extracted.gross_total);
      setNote({
        text: r.created
          ? `${period} mileage claim for ${amount} is waiting in Review for you to approve.`
          : `${period} mileage claim (${amount}) is already waiting in Review, brought up to date.`,
        review: true,
      });
      await load(account, taxYear);
    } catch (e) {
      setNote({ text: parseRuntimeError(errorText(e)).detail || "The mileage claim did not go through — try again." });
    } finally {
      setBusy(null);
    }
  }

  if (state === "checking") return <LoadingSkeleton lines={3} label="Loading your vehicles…" />;
  if (state === "off")
    return (
      <div className="flex flex-col gap-3">
        {error && <RuntimeErrorNote message={error} />}
        {note && <p className="rounded-xl bg-ground px-4 py-2 text-sm text-muted">{note.text}</p>}
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-white p-6 text-[15px] leading-7 text-muted">
          <SignInCta />
          <span>
            to keep your vehicles and mileage log in your own OneDrive. Personal cars and vans used
            for business earn 45p a mile for the first 10,000 business miles in the tax year, then 25p; motorcycles 24p;
            bicycles 20p.
          </span>
        </p>
      </div>
    );

  const byId = new Map(vehicles.map((v) => [v.id, v]));
  const today = londonToday();
  const quarter = summary?.quarters.find((q) => q.start <= today && today <= q.end) ?? null;
  const carVanPct = summary ? Math.min(100, (summary.car_van_miles / summary.threshold_miles) * 100) : 0;
  const business = summary?.vehicles.filter((v) => v.owned_by === "business") ?? [];
  // Journeys before the latest posted claim's date can't change (the runtime refuses; claimed ones on that day too).
  const locked = (e: RtMileageEntry) => Boolean(summary?.locked_until && e.date < summary.locked_until);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm font-bold">
          Tax year
          <select
            value={taxYear}
            onChange={(e) => act("year", async () => undefined, undefined, e.target.value)}
            className={input}
          >
            {[currentYear, previousTaxYear(currentYear), previousTaxYear(previousTaxYear(currentYear))].map((ty) => (
              <option key={ty} value={ty}>
                {ty.replace("-", "–")}
              </option>
            ))}
          </select>
        </label>
        {taxYear === currentYear && quarter && (
          <button type="button" disabled={busy !== null} onClick={() => claim(quarter.period)} className={button}>
            {busy === `claim-${quarter.period}` ? "Working out your claim…" : "Claim this quarter's mileage"}
          </button>
        )}
        <span className="text-sm text-muted">The claim goes to Review; nothing is posted until you approve it.</span>
      </div>

      {note && (
        <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">
          {note.text}{" "}
          {note.review && (
            <Link href="/review" className="font-bold underline underline-offset-2">
              Open Review
            </Link>
          )}
        </p>
      )}
      {error && <RuntimeErrorNote message={error} />}

      {vehicles.length === 0 && entries.length === 0 && (
        <EmptyState
          title="No vehicles yet"
          body="Add a vehicle below to log business journeys and build up your HMRC mileage allowance."
          action={
            <button
              type="button"
              onClick={() => newVehicleRef.current?.focus()}
              className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
            >
              Add your first vehicle
            </button>
          }
        />
      )}

      {summary && (
        <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1100px]:grid-cols-4">
          <Tile label={`Business miles ${summary.tax_year.replace("-", "–")}`} value={miles(summary.vehicles.reduce((n, v) => n + v.miles, 0))} sub={`${entries.length} journeys logged`} />
          <Tile label="Mileage allowance so far" value={pounds(summary.allowance_pence)} sub={`${pounds(summary.claimed_pence)} claimed and posted`} />
          <Tile
            label="Cars and vans vs 10,000 miles"
            value={`${miles(summary.car_van_miles)} mi`}
            sub={summary.threshold_crossed_on ? `25p a mile since ${ukDate(summary.threshold_crossed_on)}` : `${miles(Math.max(0, summary.threshold_miles - summary.car_van_miles))} mi left at 45p`}
            bar={carVanPct}
          />
          <Tile
            label="Business vehicle costs"
            value={pounds(business.reduce((n, v) => n + v.cost_pence, 0))}
            sub={`${business.reduce((n, v) => n + v.cost_entries, 0)} receipts tagged this tax year`}
          />
        </div>
      )}

      {summary && (
        <section aria-labelledby="quarters" className="rounded-2xl border border-border bg-white p-5">
          <h2 id="quarters" className="text-[17px] font-extrabold">
            Quarters
          </h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-[15px]">
              <thead>
                <tr className="border-b border-border text-[13px] font-bold text-muted">
                  <th scope="col" className="py-2 pr-3">Quarter</th>
                  <th scope="col" className="py-2 pr-3 text-right">Miles</th>
                  <th scope="col" className="py-2 pr-3 text-right">Allowance</th>
                  <th scope="col" className="py-2 pr-3 text-right">Claimed</th>
                  <th scope="col" className="py-2 pr-3 text-right">Not yet claimed</th>
                  <th scope="col" className="py-2"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {summary.quarters.map((q) => (
                  <tr key={q.period} className="border-t border-border">
                    <th scope="row" className="py-2 pr-3 font-bold">
                      {q.period} <span className="font-normal text-muted">{ukDate(q.start)} – {ukDate(q.end)}</span>
                    </th>
                    <td className="py-2 pr-3 text-right tabular-nums">{miles(q.miles)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{pounds(q.allowance_pence)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{pounds(q.claimed_pence)}</td>
                    <td className="py-2 pr-3 text-right font-bold tabular-nums">{pounds(q.unclaimed_pence)}</td>
                    <td className="py-2 text-right">
                      {q.waiting_claim_id ? (
                        <Link href="/review" className="text-sm font-bold text-teal underline underline-offset-2">
                          Waiting in Review
                        </Link>
                      ) : q.unclaimed_pence > 0 && q.start <= today ? (
                        <button type="button" disabled={busy !== null} onClick={() => claim(q.period)} className="text-sm font-bold text-teal underline underline-offset-2 disabled:opacity-60">
                          {busy === `claim-${q.period}` ? "Working…" : `Claim ${q.period}`}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section aria-labelledby="mileage-log" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="mileage-log" className="text-[17px] font-extrabold">
          Mileage log
        </h2>
        <p className="mt-1 text-sm text-muted">
          Business journeys only (not home to your usual workplace). Miles in steps of 0.1.
          {summary?.locked_until && ` Mileage up to ${ukDate(summary.locked_until)} has been claimed, so earlier journeys can't be changed (undo the claim in Review first).`}
        </p>
        {vehicles.some((v) => v.active) ? (
          <form
            className="mt-3 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const body = { ...trip, miles: Number(trip.miles), job_id: null };
              act("trip", async () => {
                await runtime.addMileage(account!, body);
                setTrip((t) => ({ ...t, from: "", to: "", miles: "", purpose: "" }));
              }, `Logged ${body.miles} miles`, taxYearOf(body.date));
            }}
          >
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Vehicle
              <select required value={trip.vehicle_id} onChange={(e) => setTrip({ ...trip, vehicle_id: e.target.value })} className={input}>
                {vehicles.filter((v) => v.active).map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Date
              <input required type="date" max={today} value={trip.date} onChange={(e) => setTrip({ ...trip, date: e.target.value })} className={input} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              From
              <input value={trip.from} onChange={(e) => setTrip({ ...trip, from: e.target.value })} className={`${input} w-32`} placeholder="Leeds" />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              To
              <input value={trip.to} onChange={(e) => setTrip({ ...trip, to: e.target.value })} className={`${input} w-32`} placeholder="York" />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Miles
              <input required type="number" min="0.1" max="2000" step="0.1" inputMode="decimal" value={trip.miles} onChange={(e) => setTrip({ ...trip, miles: e.target.value })} className={`${input} w-24`} />
            </label>
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-[13px] font-bold text-muted">
              Purpose
              <input required value={trip.purpose} onChange={(e) => setTrip({ ...trip, purpose: e.target.value })} className={input} placeholder="Quote for kitchen, Mrs Patel" />
            </label>
            <button type="submit" disabled={busy !== null} className={button}>
              {busy === "trip" ? "Saving…" : "Add journey"}
            </button>
          </form>
        ) : (
          <p className="mt-3 text-sm text-muted">Add a vehicle below to start logging journeys.</p>
        )}
        {editingId && (
          <form
            aria-label="Edit journey"
            className="mt-3 flex flex-wrap items-end gap-2 rounded-xl bg-ground p-3"
            onSubmit={(e) => {
              e.preventDefault();
              const id = editingId;
              const body = { ...editTrip, miles: Number(editTrip.miles) };
              const after = body.date;
              act(`edit-${id}`, () => runtime.updateMileage(account!, id, body), "Journey updated", taxYearOf(after)).then((ok) => {
                if (ok) setEditingId(null);
              });
            }}
          >
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Vehicle
              <select value={editTrip.vehicle_id} onChange={(e) => setEditTrip({ ...editTrip, vehicle_id: e.target.value })} className={input}>
                {vehicles.filter((v) => v.active).map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Date
              <input required type="date" max={today} value={editTrip.date} onChange={(e) => setEditTrip({ ...editTrip, date: e.target.value })} className={input} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              From
              <input value={editTrip.from} onChange={(e) => setEditTrip({ ...editTrip, from: e.target.value })} className={`${input} w-32`} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              To
              <input value={editTrip.to} onChange={(e) => setEditTrip({ ...editTrip, to: e.target.value })} className={`${input} w-32`} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Miles
              <input required type="number" min="0.1" max="2000" step="0.1" inputMode="decimal" value={editTrip.miles} onChange={(e) => setEditTrip({ ...editTrip, miles: e.target.value })} className={`${input} w-24`} />
            </label>
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-[13px] font-bold text-muted">
              Purpose
              <input required value={editTrip.purpose} onChange={(e) => setEditTrip({ ...editTrip, purpose: e.target.value })} className={input} />
            </label>
            <button type="submit" disabled={busy !== null} className={button}>
              {busy === `edit-${editingId}` ? "Saving…" : "Save journey"}
            </button>
            <button type="button" onClick={() => setEditingId(null)} className={quiet}>
              Cancel
            </button>
          </form>
        )}
        {entries.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-[15px]">
              <thead>
                <tr className="border-b border-border text-[13px] font-bold text-muted">
                  <th scope="col" className="py-2 pr-3">Date</th>
                  <th scope="col" className="py-2 pr-3">Vehicle</th>
                  <th scope="col" className="py-2 pr-3">Journey</th>
                  <th scope="col" className="py-2 pr-3 text-right">Miles</th>
                  <th scope="col" className="py-2 pr-3">Purpose</th>
                  <th scope="col" className="py-2"><span className="sr-only">Change</span></th>
                </tr>
              </thead>
              <tbody>
                {[...entries].reverse().map((e) => (
                  <tr key={e.id} className="border-t border-border">
                    <td className="py-2 pr-3 whitespace-nowrap">{ukDate(e.date)}</td>
                    <td className="py-2 pr-3">{byId.get(e.vehicle_id)?.name ?? "—"}</td>
                    <td className="py-2 pr-3">{e.from || e.to ? `${e.from || "?"} → ${e.to || "?"}` : "—"}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{miles(e.miles)}</td>
                    <td className="py-2 pr-3">{e.purpose}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {locked(e) ? (
                        <span className="text-sm text-muted">Locked</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => {
                              setEditingId(e.id);
                              setEditTrip({ vehicle_id: e.vehicle_id, date: e.date, from: e.from ?? "", to: e.to ?? "", miles: String(e.miles), purpose: e.purpose });
                            }}
                            aria-label={`Edit the journey on ${ukDate(e.date)}`}
                            className="text-sm font-bold text-teal underline underline-offset-2 disabled:opacity-60"
                          >
                            Edit
                          </button>
                          {" · "}
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => act(e.id, () => runtime.deleteMileage(account!, e.id), "Journey deleted")}
                            aria-label={`Delete the journey on ${ukDate(e.date)}`}
                            className="text-sm font-bold text-muted underline underline-offset-2 disabled:opacity-60"
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="vehicles" className="rounded-2xl border border-border bg-white p-5">
        <h2 id="vehicles" className="text-[17px] font-extrabold">
          Vehicles
        </h2>
        <p className="mt-1 text-sm text-muted">
          Personal vehicles earn the mileage allowance. Business-owned vehicles don&apos;t: tag their fuel, parking and
          repair receipts to them in Review and the actual costs count instead.
        </p>
        {summary && summary.vehicles.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-[15px]">
              <thead>
                <tr className="border-b border-border text-[13px] font-bold text-muted">
                  <th scope="col" className="py-2 pr-3">Vehicle</th>
                  <th scope="col" className="py-2 pr-3">Owned by</th>
                  <th scope="col" className="py-2 pr-3 text-right">Business miles</th>
                  <th scope="col" className="py-2 pr-3 text-right">Allowance / costs</th>
                  <th scope="col" className="py-2 pr-3 text-right">Per mile</th>
                  <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {summary.vehicles.map((v) => (
                  <tr key={v.vehicle_id} className={`border-t border-border ${v.active ? "" : "text-muted"}`}>
                    <th scope="row" className="py-2 pr-3 font-bold">
                      {v.name}
                      <span className="block text-[13px] font-normal text-muted">
                        {[v.registration, v.kind, v.active ? null : "inactive"].filter(Boolean).join(" · ")}
                      </span>
                    </th>
                    <td className="py-2 pr-3">{v.owned_by === "business" ? "Business" : "Personal"}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{miles(v.miles)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {v.owned_by === "business" ? `${pounds(v.cost_pence)} · ${v.cost_entries} receipts` : pounds(v.allowance_pence)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{v.pence_per_mile !== null ? `${v.pence_per_mile}p` : "—"}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => {
                          setRenamingId(v.vehicle_id);
                          setRename({ name: v.name, registration: v.registration ?? "" });
                        }}
                        aria-label={`Rename ${v.name}`}
                        className="text-sm font-bold text-teal underline underline-offset-2 disabled:opacity-60"
                      >
                        Rename
                      </button>
                      {" · "}
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => act(v.vehicle_id, () => runtime.updateVehicle(account!, v.vehicle_id, { active: !v.active }))}
                        className="text-sm font-bold text-teal underline underline-offset-2 disabled:opacity-60"
                      >
                        {v.active ? "Mark inactive" : "Make active"}
                      </button>
                      {" · "}
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() =>
                          act(v.vehicle_id, () => runtime.deleteVehicle(account!, v.vehicle_id), `Deleted ${v.name}`, taxYear)
                        }
                        aria-label={`Delete ${v.name}`}
                        className="text-sm font-bold text-muted underline underline-offset-2 disabled:opacity-60"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {renamingId && (
          <form
            aria-label="Rename vehicle"
            className="mt-3 flex flex-wrap items-end gap-2 rounded-xl bg-ground p-3"
            onSubmit={(e) => {
              e.preventDefault();
              const id = renamingId;
              const body = { name: rename.name.trim(), registration: rename.registration.trim() || null };
              act(`rename-${id}`, () => runtime.updateVehicle(account!, id, body), `Renamed to ${body.name}`).then((ok) => {
                if (ok) setRenamingId(null);
              });
            }}
          >
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Name
              <input required maxLength={60} value={rename.name} onChange={(e) => setRename({ ...rename, name: e.target.value })} className={input} />
            </label>
            <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
              Registration (optional)
              <input maxLength={12} value={rename.registration} onChange={(e) => setRename({ ...rename, registration: e.target.value })} className={`${input} w-36`} />
            </label>
            <button type="submit" disabled={busy !== null} className={button}>
              {busy === `rename-${renamingId}` ? "Saving…" : "Save name"}
            </button>
            <button type="button" onClick={() => setRenamingId(null)} className={quiet}>
              Cancel
            </button>
          </form>
        )}
        <form
          className="mt-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const body = { ...newVehicle, registration: newVehicle.registration.trim() || null, active: true };
            act("vehicle", async () => {
              await runtime.addVehicle(account!, body);
              setNewVehicle({ ...newVehicle, name: "", registration: "" });
            }, `Added ${body.name}`);
          }}
        >
          <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
            Name
            <input ref={newVehicleRef} required maxLength={60} value={newVehicle.name} onChange={(e) => setNewVehicle({ ...newVehicle, name: e.target.value })} className={input} placeholder="Ford Transit" />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
            Registration (optional)
            <input maxLength={12} value={newVehicle.registration} onChange={(e) => setNewVehicle({ ...newVehicle, registration: e.target.value })} className={`${input} w-36`} />
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
            Type
            <select value={newVehicle.kind} onChange={(e) => setNewVehicle({ ...newVehicle, kind: e.target.value as RtVehicleKind })} className={input}>
              {KINDS.map((k) => (
                <option key={k} value={k}>{k[0].toUpperCase() + k.slice(1)}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-bold text-muted">
            Owned by
            <select value={newVehicle.owned_by} onChange={(e) => setNewVehicle({ ...newVehicle, owned_by: e.target.value as "personal" | "business" })} className={input}>
              <option value="personal">Me (personal)</option>
              <option value="business">The business</option>
            </select>
          </label>
          <button type="submit" disabled={busy !== null} className={quiet}>
            {busy === "vehicle" ? "Adding…" : "Add vehicle"}
          </button>
        </form>
      </section>

      {summary && (
        <section aria-labelledby="mileage-rules" className="rounded-2xl bg-ground p-5">
          <h2 id="mileage-rules" className="text-[15px] font-extrabold">
            How it&apos;s worked out
          </h2>
          <ul className="mt-2 flex flex-col gap-1 text-[14px] leading-6">
            {summary.rates.map((r) => (
              <li key={r.kind}>
                {r.kind[0].toUpperCase() + r.kind.slice(1)}s: {r.first_pence}p a mile
                {r.threshold_miles ? ` for the first ${r.threshold_miles.toLocaleString("en-GB")} business miles (cars and vans together), then ${r.after_pence}p` : ""}
              </li>
            ))}
            <li>Tax year {ukDate(summary.start)} – {ukDate(summary.end)}. HMRC approved mileage rates, calculated by code.</li>
          </ul>
          {summary.notes.map((n) => (
            <p key={n} className="mt-2 text-[14px] leading-6 text-muted">
              {n}
            </p>
          ))}
        </section>
      )}
    </div>
  );
}

function Tile({ label, value, sub, bar }: { label: string; value: string; sub: string; bar?: number }) {
  return (
    <div className="rounded-2xl border border-border bg-white p-4">
      <p className="text-sm font-semibold text-muted">{label}</p>
      <p className="mt-1 text-2xl font-extrabold tracking-tight text-ink">{value}</p>
      {bar !== undefined && (
        <div className="mt-2 h-2 rounded-full bg-ground" role="progressbar" aria-valuenow={Math.round(bar)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
          <div className="h-2 rounded-full bg-teal" style={{ width: `${bar}%` }} />
        </div>
      )}
      <p className="mt-1 text-[13px] font-semibold text-muted">{sub}</p>
    </div>
  );
}
