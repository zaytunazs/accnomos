"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { pence, runtime, type RtStaff, type RtStaffIn } from "@/lib/runtime";
import { errorText, useAccount } from "@/components/jobs/useAccount";

type Draft = { name: string; role: string; hourly: string; charge: string; active: boolean };
const EMPTY: Draft = { name: "", role: "", hourly: "", charge: "", active: true };

/** "12.50" -> 1250; blank -> null. NaN for anything that isn't a non-negative amount. */
function toPence(v: string): number | null {
  const t = v.replace(/[£,\s]/g, "");
  if (!t) return null;
  return /^\d+(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 100) : NaN;
}

const fromPence = (p: number | null) => (p === null ? "" : (p / 100).toFixed(2));
const field = "h-10 rounded-xl border border-border px-2 text-sm";

/** Settings › Staff: names, roles and rates in _System/Staff/staff.json (no other personal details). */
export default function StaffEditor({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [staff, setStaff] = useState<RtStaff[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // staff id, or "new"
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      setStaff(await runtime.staff(account));
    } catch (e) {
      setNote(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  function edit(s: RtStaff | null) {
    setNote(null);
    setEditing(s ? s.id : "new");
    setDraft(s ? { name: s.name, role: s.role, hourly: fromPence(s.hourly_rate_pence), charge: fromPence(s.charge_rate_pence), active: s.active } : EMPTY);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!account || !editing) return;
    const hourly = toPence(draft.hourly);
    const charge = toPence(draft.charge);
    if (hourly === null || Number.isNaN(hourly) || Number.isNaN(charge)) {
      setNote("Rates are pounds per hour, e.g. 18.50 (charge rate may be left blank).");
      return;
    }
    const body: RtStaffIn = { name: draft.name.trim(), role: draft.role.trim(), hourly_rate_pence: hourly, charge_rate_pence: charge, active: draft.active };
    setBusy(true);
    try {
      if (editing === "new") await runtime.createStaff(account, body);
      else await runtime.updateStaff(account, editing, body);
      setEditing(null);
      setNote("Saved.");
      await load();
    } catch (err) {
      setNote(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const form = (
    <tr>
      <td colSpan={5} className="py-3">
        <form onSubmit={save} className="flex flex-wrap items-end gap-2" aria-label="Staff member">
          <label className="flex flex-col gap-1 text-xs font-bold text-muted">
            Name
            <input required value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className={field} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-bold text-muted">
            Role
            <input value={draft.role} maxLength={120} placeholder="e.g. Electrician" onChange={(e) => setDraft({ ...draft, role: e.target.value })} className={field} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-bold text-muted">
            Cost £/h
            <input required inputMode="decimal" value={draft.hourly} onChange={(e) => setDraft({ ...draft, hourly: e.target.value })} className={`${field} w-24`} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-bold text-muted">
            Charge £/h
            <input inputMode="decimal" value={draft.charge} placeholder="at cost" onChange={(e) => setDraft({ ...draft, charge: e.target.value })} className={`${field} w-24`} />
          </label>
          <label className="flex h-10 items-center gap-2 text-sm font-semibold text-ink">
            <input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />
            Active
          </label>
          <button type="submit" disabled={busy || !draft.name.trim()} className="h-10 rounded-xl bg-teal px-4 text-sm font-extrabold text-white disabled:opacity-60">
            {busy ? "Saving…" : "Save"}
          </button>
          <button type="button" onClick={() => setEditing(null)} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink">
            Cancel
          </button>
        </form>
      </td>
    </tr>
  );

  return (
    <section aria-labelledby="settings-staff" className={card}>
      <div className="flex items-center justify-between gap-3">
        <h2 id="settings-staff" className={heading}>
          Staff
        </h2>
        {account && staff && editing === null && (
          <button type="button" onClick={() => edit(null)} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold text-ink">
            Add person
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        Who works on your jobs, what an hour costs you and what you charge for it. Only names and roles are kept: no other personal
        details. People with hours can be marked inactive but not removed.
      </p>
      {staff === null ? (
        <p className="mt-3 text-sm text-muted">{account === null ? "Sign in to manage staff." : (note ?? "Loading…")}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Name</th>
                <th scope="col" className="py-2 pr-3">Role</th>
                <th scope="col" className="py-2 pr-3 text-right">Cost /h</th>
                <th scope="col" className="py-2 pr-3 text-right">Charge /h</th>
                <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {editing === "new" && form}
              {staff.length === 0 && editing === null && (
                <tr>
                  <td colSpan={5} className="py-2 text-muted">No staff yet.</td>
                </tr>
              )}
              {staff.map((s) =>
                editing === s.id ? (
                  <Fragment key={s.id}>{form}</Fragment>
                ) : (
                  <tr key={s.id} className={s.active ? "text-ink" : "text-muted"}>
                    <td className="py-2 pr-3 font-bold">
                      {s.name}
                      {!s.active && <span className="ml-2 rounded-full bg-ground px-2 py-0.5 text-[11px] font-extrabold">Inactive</span>}
                    </td>
                    <td className="py-2 pr-3">{s.role || "—"}</td>
                    <td className="py-2 pr-3 text-right">{pence(s.hourly_rate_pence)}</td>
                    <td className="py-2 pr-3 text-right">{s.charge_rate_pence === null ? "at cost" : pence(s.charge_rate_pence)}</td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        disabled={editing !== null}
                        onClick={() => edit(s)}
                        aria-label={`Edit ${s.name}`}
                        className="h-9 rounded-xl border border-border bg-white px-3 text-[13px] font-bold text-ink disabled:opacity-60"
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      {note && staff !== null && (
        <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </section>
  );
}
