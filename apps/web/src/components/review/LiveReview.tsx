"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { warmServerAi } from "@/lib/meta-models";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import ReviewQueue, { type ReviewAdapter } from "@/components/review/ReviewQueue";
import SignInCta from "@/components/SignInCta";
import UploadToInbox from "@/components/review/UploadToInbox";
import ScanProgress from "@/components/review/ScanProgress";
import { onScanFiled, trackScanJob } from "@/lib/scan-jobs";
import { VatCheckButton, useLookupStatus } from "@/components/contacts/Lookups";
import {
  EmptyState,
  LoadingSkeleton,
  ReaderErrorNote,
  RuntimeErrorNote,
  SamplePill,
  isReaderError,
} from "@/components/States";
import { getFileBlob } from "@/lib/graph";
import { getMsal, msalConfigured } from "@/lib/msal";
import { autopilotLevel, gbp, runtime, ukDate, type RtJob, type RtProposal, type RtRule, type RtVehicle } from "@/lib/runtime";
import { SAMPLE_IMAGE, sampleProposals, sampleRules } from "@/lib/sample-review";

type Mode = "checking" | "demo" | "live";
type Level = ReturnType<typeof autopilotLevel>;

const AUTOPILOT_WINDOW_DAYS = 30; // how long Autopilot postings stay listed for Undo

function Notes({ note, error }: { note: string | null; error: string | null }) {
  return (
    <>
      <p role="status" aria-live="polite" className={note ? "rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark" : "sr-only"}>
        {note}
      </p>
      {error &&
        (isReaderError(error) ? (
          <ReaderErrorNote detail={error} />
        ) : (
          <RuntimeErrorNote message={error} />
        ))}
    </>
  );
}

/** Signed out: the same queue over fictional proposals. Every decision stays in this tab. */
function SampleReview({ note: initialNote, level }: { note: string | null; level: Level }) {
  const [items, setItems] = useState<RtProposal[]>(sampleProposals);
  const [note, setNote] = useState<string | null>(initialNote);
  const [error, setError] = useState<string | null>(null);

  const adapter = useMemo<ReviewAdapter<string>>(() => {
    const order = sampleProposals().map((p) => p.id); // undo puts a card back where it was
    const remove = (p: RtProposal) => setItems((xs) => xs.filter((x) => x.id !== p.id));
    const restore = (id: string) =>
      setItems((xs) =>
        [...xs.filter((x) => x.id !== id), sampleProposals().find((s) => s.id === id)!].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)),
      );
    return {
      approve: async (p) => (remove(p), p.id),
      reject: async (p) => remove(p),
      undo: async (id) => restore(id),
      unreject: async (p) => restore(p.id),
      image: (p) => (p.id === "sample-novex" ? { url: SAMPLE_IMAGE } : null),
    };
  }, []);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-ink">
        <SamplePill />
        <span>
          <strong>Fictional Bramblewood Joinery Ltd books.</strong>{" "}
          Decisions here stay in this tab; nothing is posted anywhere.
        </span>
        <SignInCta />
      </p>
      <Notes note={note} error={error} />
      <ReviewQueue items={items} rules={sampleRules} level={level} adapter={adapter} onNote={setNote} onError={setError} />
      {items.length === 0 && (
        <EmptyState title="All sample cards decided" body="Press U to undo the last approval, or reload the page to start the sample again." />
      )}
    </div>
  );
}

export default function LiveReview() {
  const [mode, setMode] = useState<Mode>("checking");
  const [level, setLevel] = useState<Level>("L1");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const lookups = useLookupStatus();
  const [items, setItems] = useState<RtProposal[]>([]);
  const [rules, setRules] = useState<RtRule[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoPosted, setAutoPosted] = useState<RtProposal[]>([]);
  const [openJobs, setOpenJobs] = useState<RtJob[]>([]);
  const [jobFor, setJobFor] = useState<Record<string, string>>({});
  const [businessVehicles, setBusinessVehicles] = useState<RtVehicle[]>([]);
  const [vehicleFor, setVehicleFor] = useState<Record<string, string>>({});

  const load = useCallback(async (acct: AccountInfo) => {
    const [proposed, flagged, posted, saved] = await Promise.all([
      runtime.proposals(acct, "proposed"),
      runtime.proposals(acct, "needs_a_look"),
      runtime.proposals(acct, "posted"),
      runtime.rules(acct).catch(() => [] as RtRule[]), // no rules file yet: no rule matches
    ]);
    setItems([...proposed, ...flagged]);
    setRules(saved);
    const since = Date.now() - AUTOPILOT_WINDOW_DAYS * 86_400_000;
    setAutoPosted(posted.filter((p) => p.decided_by === "autopilot" && p.event_id && new Date(p.decided_at ?? 0).getTime() >= since));
    setOpenJobs(await runtime.openJobs(acct).catch(() => [])); // no jobs feature in use: no picker
    const vehicles = await runtime.vehicles(acct).catch(() => []); // no vehicles file yet: no picker
    setBusinessVehicles(vehicles.filter((v) => v.owned_by === "business" && v.active));
  }, []);

  useEffect(() => {
    (async () => {
      setLevel(autopilotLevel());
      try {
        if (!msalConfigured()) return setMode("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setMode("demo");
        setAccount(acct);
        warmServerAi(); // a cold Modal container starts now, not on the first upload
        await load(acct);
        setMode("live");
      } catch (e) {
        setNote(`Showing sample data — ${(e as Error).message}`);
        setMode("demo");
      }
    })();
  }, [load]);

  const adapter = useMemo<ReviewAdapter<string> | null>(
    () =>
      account && {
        approve: async (p, body) => (await runtime.approve(account, p.id, body)).event_id ?? null,
        reject: async (p) => void (await runtime.reject(account, p.id, "rejected by user")),
        undo: async (eventId) => (await runtime.undo(account, eventId)).reason ?? undefined,
        image: (p) => (p.file_path ? { load: () => getFileBlob(account, p.file_path!) } : null),
      },
    [account],
  );

  /** Undo one Autopilot approval: the toast names the open period when the entry's VAT period was already submitted. */
  async function undoAutopilot(p: RtProposal) {
    if (!account || !p.event_id) return;
    setBusy(p.id);
    setError(null);
    try {
      const r = await runtime.undo(account, p.event_id);
      setNote(
        r.reason
          ? `${r.reason} It is back in Review.`
          : "Undone · a reversing entry was added; it is back in Review",
      );
      await load(account);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  // Background scans (ScanProgress): reload the cards each time another file reaches Review or Needs a look.
  // Announced once the cards are on the page, so J (or a screen-reader user) never acts on an empty queue.
  useEffect(
    () =>
      onScanFiled((n) => {
        if (!account) return;
        void load(account).then(() => n > 0 && setNote(`${n} new proposal${n === 1 ? "" : "s"}`));
      }),
    [account, load],
  );

  /** Starts a background job over every file in 00 Inbox; the answer comes at once, the progress below. */
  async function scan() {
    if (!account) return;
    setBusy("scan");
    setError(null);
    try {
      const job = await runtime.startScan(account, undefined, "inbox");
      trackScanJob(job);
      setNote(job.files.length ? `Reading ${job.files.length} file${job.files.length === 1 ? "" : "s"} from 00 Inbox` : "00 Inbox is empty");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  /** Job and vehicle tags chosen under a card, sent as edits only when they change something. */
  function pickerEdits(p: RtProposal): Record<string, unknown> {
    const job = p.extracted.doc_type === "sales_invoice" ? "" : (jobFor[p.id] ?? "");
    const picked = vehicleFor[p.id]; // "" clears a pre-filled vehicle
    const vehicleEdit = picked !== undefined && picked !== (p.vehicle_id ?? "") ? { vehicle_id: picked || null } : {};
    return { ...(job ? { job_id: job } : {}), ...vehicleEdit };
  }

  function pickers(p: RtProposal) {
    const job = openJobs.length > 0 && p.extracted.doc_type !== "sales_invoice";
    const vehicle = p.extracted.doc_type !== "sales_invoice" && !p.mileage_claim && (businessVehicles.length > 0 || p.vehicle_id);
    // No business vehicle yet: offer to add one rather than hiding vehicle tagging altogether.
    const vehicleAdd = p.extracted.doc_type !== "sales_invoice" && !p.mileage_claim && businessVehicles.length === 0 && !p.vehicle_id;
    // Only on a tap, never on every scan; the answer is kept on the supplier's contact. Never blocks Approve.
    const vrn = p.extracted.doc_type !== "sales_invoice" ? p.extracted.supplier_vat_number?.trim() : "";
    const vat = account && vrn && lookups?.vat_check ? (
      <VatCheckButton key={`${p.id}-${vrn}`} account={account} vrn={vrn} name={p.extracted.supplier_name} />
    ) : null;
    if (!job && !vehicle && !vehicleAdd) return vat;
    return (
      <div className="flex flex-wrap gap-2">
        {vat && <div className="basis-full">{vat}</div>}
        {job && (
          <label className="flex items-center gap-2 text-sm font-bold text-ink">
            Job
            <select
              value={jobFor[p.id] ?? ""}
              onChange={(e) => setJobFor((j) => ({ ...j, [p.id]: e.target.value }))}
              className="h-11 max-w-[14rem] rounded-xl border border-border bg-white px-3 font-normal"
            >
              <option value="">None</option>
              {openJobs.map((j) => (
                <option key={j.id} value={j.id}>{j.name}</option>
              ))}
            </select>
          </label>
        )}
        {vehicle && (
          <label className="flex items-center gap-2 text-sm font-bold text-ink">
            Vehicle
            <select
              value={vehicleFor[p.id] ?? p.vehicle_id ?? ""}
              onChange={(e) => setVehicleFor((v) => ({ ...v, [p.id]: e.target.value }))}
              className="h-11 max-w-[14rem] rounded-xl border border-border bg-white px-3 font-normal"
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
        {vehicleAdd && (
          <p className="text-sm text-muted">
            Vehicle:{" "}
            <Link href="/vehicles" className="font-bold text-teal underline underline-offset-2">
              Add a vehicle
            </Link>{" "}
            to tag fuel and repair receipts to it.
          </p>
        )}
      </div>
    );
  }

  if (mode === "checking")
    return <LoadingSkeleton lines={3} label="Loading your proposals…" />;
  if (mode === "demo") return <SampleReview note={note} level={level} />;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={scan} disabled={busy !== null} className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60">
          {busy === "scan" ? "Starting…" : "Scan 00 Inbox now"}
        </button>
        <UploadToInbox account={account!} onDone={() => setNote(null)} />
        <span className="text-sm text-muted">or drop files into OneDrive › Apps › Accnomos › 00 Inbox</span>
      </div>
      <Notes note={note} error={error} />
      {account && <ScanProgress account={account} />}
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
                  onClick={() => undoAutopilot(p)}
                  className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
                >
                  {busy === p.id ? "Working…" : "Undo"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <ReviewQueue
        items={items}
        rules={rules}
        level={level}
        adapter={adapter!}
        onNote={setNote}
        onError={setError}
        approveEdits={pickerEdits}
        extras={pickers}
        afterDecision={() => load(account!)}
      />
      {items.length === 0 && (
        <EmptyState
          title="No receipts waiting"
          body="Receipts you scan or upload appear here for you to approve before anything reaches your books."
          action={<UploadToInbox account={account!} onDone={() => account && load(account)} />}
        />
      )}
    </div>
  );
}
