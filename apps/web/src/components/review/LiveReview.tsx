"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import ProposalCard from "@/components/review/ProposalCard";
import UploadToInbox from "@/components/review/UploadToInbox";
import {
  EmptyState,
  ErrorNote,
  LoadingSkeleton,
  ReaderErrorNote,
  isReaderError,
} from "@/components/States";
import { getMsal, msalConfigured } from "@/lib/msal";
import { gbp, runtime, ukDate, type RtJob, type RtProposal, type RtVehicle } from "@/lib/runtime";
import type { Proposal as UiProposal } from "@/lib/sample-review";

type Mode = "checking" | "demo" | "live";

const AUTOPILOT_WINDOW_DAYS = 30; // how long Autopilot postings stay listed for Undo

const codeMeaning: Record<string, string> = {
  S: "standard-rated 20%",
  R: "reduced-rated 5%",
  Z: "zero-rated",
  E: "exempt",
  N: "no VAT reclaim (no VAT invoice)",
  O: "outside the scope of UK VAT",
};

const fieldLabel: Record<string, string> = {
  supplier_name: "Supplier",
  supplier_vat_number: "VAT number",
  date: "Date",
  net_total: "Net",
  vat_total: "VAT",
  gross_total: "Total",
};

const verifierName = (model: string) =>
  model.startsWith("baseten:") ? "Muse Spark Open" : model.startsWith("meta:") ? "Muse Spark" : model.replace(/^ollama:/, "");

const shown = (v: string | number | null) => (v === null || v === "" ? "none" : typeof v === "number" ? v.toFixed(2) : v);

/** The verifier chip, bound to the runtime's real second reading. Never claims agreement it did not see. */
function verifierView(p: RtProposal): Pick<UiProposal, "verifierNote" | "verifierTone" | "verifierDiffs"> {
  const v = p.verification;
  const passed = `Checks run by code: ${p.checks.filter((c) => c.ok).length} of ${p.checks.length} passed`;
  if (!v) {
    const why = p.status === "needs_a_look" ? "skipped, checks already flagged it" : "not run";
    return { verifierNote: `Second reading ${why} · ${passed}`, verifierTone: "none" };
  }
  if (v.error) return { verifierNote: `Second reading unavailable (${v.model}) · ${passed}`, verifierTone: "none" };
  const fields = Object.entries(v.fields);
  if (v.agree_all)
    return { verifierNote: `Verifier agrees · all ${fields.length} fields match — ${verifierName(v.model)} · ${passed}`, verifierTone: "agree" };
  const diffs = fields
    .filter(([, f]) => !f.agree)
    .map(([k, f]) => ({ field: fieldLabel[k] ?? k, extractor: shown(f.extractor), verifier: shown(f.verifier) }));
  return {
    verifierNote: `Verifier disagrees on ${diffs.length} of ${fields.length} fields — ${verifierName(v.model)}. Check the document before you approve.`,
    verifierTone: "differ",
    verifierDiffs: diffs,
  };
}

/** Append the model/timing/crop suffix to the verifier line so the card keeps showing how the reading was made. */
function withCrop<T extends { verifierNote: string }>(view: T, suffix: string): T {
  return { ...view, verifierNote: `${view.verifierNote} · ${suffix}` };
}

/** Map a runtime proposal onto the card's display model (strings only, plain English). */
export function toUi(p: RtProposal): UiProposal {
  const x = p.extracted;
  const local = p.model.startsWith("local:");
  const lines = p.journal_draft.map((l) => {
    const amt = gbp((l.debit_pence || l.credit_pence) / 100);
    const isVat = l.account.includes("2200");
    const isSettle = l.credit_pence > 0 && !isVat && x.doc_type !== "sales_invoice";
    const owed = isSettle && l.account.startsWith("2300"); // mileage allowance: the business owes you
    const label = isVat ? "VAT to reclaim" : owed ? "Owed to you" : isSettle ? `Paid from ${x.payment_method === "cash" ? "cash" : "business card"}` : l.account.replace(/^\d{4}\s/, "");
    const meaning = isVat ? "Goes to Box 4" : owed ? "You paid for the journeys; pay yourself back when you like" : isSettle ? "Will match a bank line" : `Expense, ${codeMeaning[l.vat_code ?? ""] ?? "VAT as shown"}`;
    return { account: `${label} ${amt}`, amount: amt, meaning };
  });
  const fails = p.checks.filter((c) => !c.ok);
  const verified = p.checks.filter((c) => !["CROP", "VEHICLE", "MILEAGE"].includes(c.code)); // notes, not checks
  const cropped = p.crop && p.crop.method !== "none" ? ` · ${p.crop.note}` : "";
  const mileageNote = p.checks.find((c) => c.code === "MILEAGE");
  const why = fails.length
    ? `Why it's flagged: ${fails.map((c) => c.message).join("; ")}.`
    : mileageNote
      ? `Why: ${mileageNote.message}. Your mileage log is the evidence; change it on Vehicles, not here.`
      : `Why: ${x.lines.length} line${x.lines.length === 1 ? "" : "s"}, totals add up (${x.net_total.toFixed(2)} + ${x.vat_total.toFixed(2)} = ${x.gross_total.toFixed(2)}); category "${x.category_guess}". — Checker, code`;
  return {
    id: p.id,
    supplier: x.supplier_name,
    total: gbp(x.gross_total),
    confidence: `Confidence ${Math.round(x.confidence * 100)}%`,
    source: p.mileage_claim ? "Calculated by code from your mileage log" : local ? "Read by Glimmer 30B on your machine" : "Read by Muse Spark",
    date: ukDate(x.date),
    vatNumber: x.supplier_vat_number ? `${x.supplier_vat_number} ✓` : "none shown",
    net: gbp(x.net_total),
    vat: gbp(x.vat_total),
    paidBy: x.card_last4 ? `Card ending ${x.card_last4}` : (x.payment_method ?? "—"),
    lines,
    reviewerNote: why,
    ...withCrop(verifierView(p), `checks by code: ${verified.filter((c) => c.ok).length} of ${verified.length} passed · ${p.model} · ${p.elapsed_s.toFixed(1)} s${cropped}`),
  };
}

export default function LiveReview({ fallback }: { fallback: React.ReactNode }) {
  const [mode, setMode] = useState<Mode>("checking");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [items, setItems] = useState<RtProposal[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [autoPosted, setAutoPosted] = useState<RtProposal[]>([]);
  const [openJobs, setOpenJobs] = useState<RtJob[]>([]);
  const [jobFor, setJobFor] = useState<Record<string, string>>({});
  const [businessVehicles, setBusinessVehicles] = useState<RtVehicle[]>([]);
  const [vehicleFor, setVehicleFor] = useState<Record<string, string>>({});

  const load = useCallback(async (acct: AccountInfo) => {
    const [proposed, flagged, posted] = await Promise.all([
      runtime.proposals(acct, "proposed"),
      runtime.proposals(acct, "needs_a_look"),
      runtime.proposals(acct, "posted"),
    ]);
    setItems([...proposed, ...flagged]);
    const since = Date.now() - AUTOPILOT_WINDOW_DAYS * 86_400_000;
    setAutoPosted(posted.filter((p) => p.decided_by === "autopilot" && p.event_id && new Date(p.decided_at ?? 0).getTime() >= since));
    setOpenJobs(await runtime.openJobs(acct).catch(() => [])); // no jobs feature in use: no picker
    const vehicles = await runtime.vehicles(acct).catch(() => []); // no vehicles file yet: no picker
    setBusinessVehicles(vehicles.filter((v) => v.owned_by === "business" && v.active));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setMode("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setMode("demo");
        setAccount(acct);
        await load(acct);
        setMode("live");
      } catch (e) {
        setNote(`Showing sample data — ${(e as Error).message}`);
        setMode("demo");
      }
    })();
  }, [load]);

  async function act(id: string, fn: () => Promise<unknown>, done: string) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      setNote(done);
      if (account) await load(account);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function scan() {
    if (!account) return;
    setBusy("scan");
    setError(null);
    try {
      const r = await runtime.scan(account);
      const auto = r.proposals.filter((p) => p.decided_by === "autopilot").length;
      const n = r.proposals.length - auto;
      const errs = r.errors.map((e) => `${e.path.split("/").pop()}: ${e.error}`).join(" · ");
      setNote(`${n} new proposal${n === 1 ? "" : "s"}${auto ? ` · ${auto} approved by Autopilot` : ""}${errs ? ` · could not read: ${errs}` : ""}`);
      await load(account);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (mode === "checking")
    return <LoadingSkeleton lines={3} label="Loading your proposals…" />;
  if (mode === "demo")
    return (
      <>
        {note && <p className="rounded-xl bg-ground px-4 py-2 text-sm text-muted">{note}</p>}
        {fallback}
      </>
    );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={scan} disabled={busy !== null} className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60">
          {busy === "scan" ? "Reading your Inbox…" : "Scan 00 Inbox now"}
        </button>
        <UploadToInbox account={account!} onDone={() => setNote("Added to your Inbox.")} />
        <span className="text-sm text-muted">{items.length} waiting · or drop files into OneDrive › Apps › Accnomos › 00 Inbox</span>
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">{note}</p>}
      {error &&
        (isReaderError(error) ? (
          <ReaderErrorNote detail={error} />
        ) : (
          <ErrorNote title="Couldn't finish that" body={error} />
        ))}
      {autoPosted.length > 0 && (
        <section aria-labelledby="autopilot-posted" className="rounded-2xl border border-border bg-white p-5">
          <h2 id="autopilot-posted" className="text-[17px] font-extrabold">
            Approved by Autopilot ({autoPosted.length})
          </h2>
          <p className="mt-1 text-sm text-muted">
            Matched a rule you saved and passed every check. Undo adds a reversing entry and puts it back here for you to decide.
          </p>
          <ul className="mt-3 divide-y divide-border">
            {autoPosted.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="text-[15px] font-bold">
                    {p.extracted.supplier_name} · {gbp(p.extracted.gross_total)}
                  </p>
                  <p className="text-sm text-muted">
                    {ukDate(p.extracted.date)} · {p.extracted.category_guess}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => act(p.id, () => runtime.undo(account!, p.event_id!), "Undone · a reversing entry was added; it is back in Review")}
                  className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
                >
                  {busy === p.id ? "Working…" : "Undo"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {items.length === 0 && (
        <EmptyState
          title="Nothing waiting"
          body="Your books are up to date. New receipts will appear here after the next inbox scan."
        />
      )}
      {items.map((p) => (
        <div key={p.id} className="flex flex-col gap-2">
          {p.status === "needs_a_look" && (
            <div className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
              <strong>Needs a look.</strong> {p.reasons.join(" · ")}
            </div>
          )}
          {p.autopilot && !p.autopilot.auto_approve && (
            <p className="rounded-xl bg-ground px-4 py-2 text-sm text-muted">
              <strong>Autopilot left this for you:</strong> {p.autopilot.reasons.join(" · ")}
            </p>
          )}
          <ProposalCard
            proposal={toUi(p)}
            hideActions
            remember={remember[p.id] ?? false}
            onRememberChange={(v) => setRemember((r) => ({ ...r, [p.id]: v }))}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                const always = remember[p.id] ?? false;
                const sale = p.extracted.doc_type === "sales_invoice";
                const done = !always
                  ? "Approved · posted to your books"
                  : sale || p.mileage_claim
                    ? `Approved · posted to your books (Autopilot rules are for ${sale ? "purchases" : "receipts"} only)`
                    : `Approved · Autopilot will do this for ${p.extracted.supplier_name} next time`;
                const job = sale ? "" : (jobFor[p.id] ?? "");
                // Send vehicle_id only when the picker changed it ("" clears a pre-filled vehicle).
                const picked = vehicleFor[p.id];
                const vehicleEdit = picked !== undefined && picked !== (p.vehicle_id ?? "") ? { vehicle_id: picked || null } : {};
                const merged = { ...(job ? { job_id: job } : {}), ...vehicleEdit };
                const edits = Object.keys(merged).length ? merged : undefined;
                return act(p.id, () => runtime.approve(account!, p.id, { remember: always, edits }), done);
              }}
              className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60"
            >
              {busy === p.id ? "Working…" : "Approve (post to books)"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => act(p.id, () => runtime.reject(account!, p.id, "rejected by user"), "Rejected")}
              className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
            >
              Reject
            </button>
            {openJobs.length > 0 && p.extracted.doc_type !== "sales_invoice" && (
              <label className="flex items-center gap-2 text-sm font-bold text-ink">
                Job
                <select
                  value={jobFor[p.id] ?? ""}
                  onChange={(e) => setJobFor((j) => ({ ...j, [p.id]: e.target.value }))}
                  className="h-11 rounded-xl border border-border bg-white px-3 font-normal"
                >
                  <option value="">None</option>
                  {openJobs.map((j) => (
                    <option key={j.id} value={j.id}>{j.name}</option>
                  ))}
                </select>
              </label>
            )}
            {p.extracted.doc_type !== "sales_invoice" && !p.mileage_claim && (businessVehicles.length > 0 || p.vehicle_id) && (
              <label className="flex items-center gap-2 text-sm font-bold text-ink">
                Vehicle
                <select
                  value={vehicleFor[p.id] ?? p.vehicle_id ?? ""}
                  onChange={(e) => setVehicleFor((v) => ({ ...v, [p.id]: e.target.value }))}
                  className="h-11 rounded-xl border border-border bg-white px-3 font-normal"
                >
                  <option value="">None</option>
                  {businessVehicles.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.registration ? `${v.name} (${v.registration})` : v.name}
                    </option>
                  ))}
                  {p.vehicle_id && !businessVehicles.some((v) => v.id === p.vehicle_id) && (
                    <option value={p.vehicle_id}>A vehicle no longer active</option>
                  )}
                </select>
              </label>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
