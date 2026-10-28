"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Explain from "@/components/Explain";
import Modal from "@/components/review/Modal";
import QueryThisLink from "@/components/accountant/QueryThisLink";
import ProposalCard from "@/components/review/ProposalCard";
import ReviewImage, { type ImageSource } from "@/components/review/ReviewImage";
import { matchingRule, ruleEdits } from "@/lib/review-rules";
import { plainReason, toUi } from "@/lib/review-view";
import { gbp, type RtProposal, type RtRule } from "@/lib/runtime";

/** How decisions reach the books: the runtime when signed in, this tab's memory for the sample. */
export interface ReviewAdapter<H> {
  /** Post it; returns what Undo needs (the ledger event id), or null when it cannot be undone. */
  approve: (p: RtProposal, body: { edits?: Record<string, unknown>; remember?: boolean }) => Promise<H | null>;
  reject: (p: RtProposal) => Promise<void>;
  /** Reverse it; returns the runtime's correction note when the entry's VAT period was already submitted. */
  undo: (handle: H) => Promise<string | void>;
  /** Undo for a rejection; absent when the backend has none (the runtime has no un-reject). */
  unreject?: (p: RtProposal) => Promise<void>;
  image: (p: RtProposal) => ImageSource | null;
}

interface Decision<H> {
  kind: "approve" | "reject";
  ids: string[];
  what: string;
  handles: H[];
  rejected?: RtProposal;
}

const label = (p: RtProposal) => `${p.extracted.supplier_name} · ${gbp(p.extracted.gross_total)}`;

/** The edit form (and lib/review-edit) loads only when Edit is tapped, never on first paint. */
const EditSheet = dynamic(() => import("@/components/review/EditSheet"), {
  ssr: false,
  loading: () => (
    <Modal label="Edit" onClose={() => {}}>
      <p className="text-sm text-muted">Loading…</p>
    </Modal>
  ),
});
const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName) || !!t.closest("dialog[open]"));

/** Autopilot reasons that say nothing to someone at L0/L1 (it is meant to be off). */
const QUIET = new Set(["Autopilot is switched off", "No Autopilot rule for this supplier"]);
/** "Check DUPLICATE failed: Looks like…" → "Looks like…": never show a raw check code. */
const plainAutopilot = (r: string) => r.replace(/^Check [A-Z][A-Z0-9_]* (failed|warned):\s*/, "");

/**
 * The supplier VAT rule, exactly as implemented (services/runtime/app/checks.py
 * `check_vat_number_required`, app/contacts.py `supplier_knowledge`): a registered business, a purchase
 * over £250 with no VAT number and no VAT, from a supplier the books do not know yet, waits in Needs a
 * look asking "Is <supplier> VAT-registered?". The tick teaches "not registered"; a VAT number seen on
 * an approved receipt teaches "registered"; undoing the approval takes the tick back (a VAT number
 * stays learnt); Contacts can change the stored answer any time.
 */
function VatQuestionExplain({ supplier }: { supplier: string }) {
  return (
    <Explain title="Why we ask about this supplier">
      <p>
        When your business is VAT-registered and a purchase over £250 shows no VAT and no VAT number,
        code asks the books whether the supplier is VAT-registered. The books have never seen {supplier},
        so the card asks you instead: “Is {supplier} VAT-registered? Over £250 they should give a VAT
        invoice.”
      </p>
      <p>
        Ticking “{supplier} isn’t VAT-registered” on approval remembers them as not registered, so their
        receipts are not questioned again. A VAT number seen on an approved receipt remembers them as
        registered instead.
      </p>
      <p>
        Undoing the approval takes the tick back (a VAT number stays learnt: the number is evidence on
        its own). You can change the stored answer any time on Contacts.
      </p>
    </Explain>
  );
}

/** The runtime's "Is <supplier> VAT-registered?" check (services/runtime/app/checks.py); the card offers the tick for it. */
export const SUPPLIER_VAT_UNKNOWN = "SUPPLIER_VAT_UNKNOWN";
/** The approve edit that records the supplier as not VAT-registered (services/runtime/app/approve.py). */
export const NOT_VAT_REGISTERED = "supplier_not_vat_registered";
export const asksVatStatus = (p: RtProposal) => p.checks.some((c) => c.code === SUPPLIER_VAT_UNKNOWN && !c.ok);

const btn = "h-11 whitespace-nowrap rounded-xl px-4 text-[15px] font-bold disabled:opacity-60 sm:px-5";
const primary = `${btn} bg-teal text-white hover:bg-teal-dark`;
const secondary = `${btn} border border-border bg-white hover:bg-ground`;

export default function ReviewQueue<H>({
  items,
  rules,
  level,
  adapter,
  onNote,
  onError,
  approveEdits,
  extras,
  rememberable = true,
  afterDecision,
}: {
  items: RtProposal[];
  rules: RtRule[];
  level: "L0" | "L1" | "L2";
  adapter: ReviewAdapter<H>;
  onNote: (note: string) => void;
  onError: (error: string | null) => void;
  /** Extra edits from pickers outside the card (live: job and vehicle). */
  approveEdits?: (p: RtProposal) => Record<string, unknown>;
  /** Pickers shown under a card's buttons. */
  extras?: (p: RtProposal) => ReactNode;
  rememberable?: boolean;
  /** Reload after a decision (live); the sample adapter changes its own state. */
  afterDecision?: () => Promise<void>;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [bulk, setBulk] = useState(false);
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [notRegistered, setNotRegistered] = useState<Record<string, boolean>>({});
  /** Business-use percent typed under each purchase card; the proposal's own value first, else 100. */
  const [businessUse, setBusinessUse] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<Decision<H>[]>([]);
  const [focusNext, setFocusNext] = useState<string | null>(null);
  const cards = useRef(new Map<string, HTMLElement>());
  const top = useRef<HTMLHeadingElement>(null);

  const ruleFor = useMemo(() => {
    const m = new Map<string, RtRule>();
    if (level === "L1") for (const p of items) {
      const r = matchingRule(p, rules);
      if (r) m.set(p.id, r);
    }
    return m;
  }, [items, rules, level]);
  const matches = items.filter((p) => ruleFor.has(p.id));
  // One ImageSource per proposal, so a re-render never refetches the file.
  const sources = useMemo(() => new Map(items.map((p) => [p.id, adapter.image(p)])), [items, adapter]);

  // Focus follows decisions: the next card, or the queue heading when nothing is left. Never the page body.
  useEffect(() => {
    if (!focusNext) return;
    const el = focusNext === "top" ? top.current : cards.current.get(focusNext);
    if (!el) return;
    el.focus({ preventScroll: true });
    // An explicit "smooth" ignores the CSS reduced-motion rule, so ask the setting here.
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    queueMicrotask(() => {
      setActive(focusNext === "top" ? null : focusNext);
      setFocusNext(null);
    });
  }, [focusNext, items]);

  // /review#proposal-<id> (from the audit trail): scroll to that card once it is on the page.
  const [hashDone, setHashDone] = useState(false);
  useEffect(() => {
    if (hashDone || items.length === 0) return;
    const raw = /^#proposal-(.+)$/.exec(window.location.hash)?.[1];
    const id = raw ? decodeURIComponent(raw) : null;
    queueMicrotask(() => {
      setHashDone(true);
      if (id && cards.current.has(id)) setFocusNext(id);
    });
  }, [hashDone, items]);

  const neighbour = useCallback(
    (ids: string[]) => {
      const gone = new Set(ids);
      const at = items.findIndex((p) => gone.has(p.id));
      const after = items.slice(at + 1).find((p) => !gone.has(p.id));
      const before = items.slice(0, Math.max(0, at)).reverse().find((p) => !gone.has(p.id));
      return (after ?? before)?.id ?? "top";
    },
    [items],
  );

  // U pressed while busy: run once busy clears (see the keys handler), unless what was busy failed.
  const undoQueued = useRef(false);
  async function run(id: string, fn: () => Promise<void>) {
    setBusy(id);
    onError(null);
    try {
      await fn();
      await afterDecision?.();
    } catch (e) {
      undoQueued.current = false; // the press meant "undo that", which never happened: don't undo the decision before it
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  /** The card's business-use percent edit: none on sales and mileage, {} at 100 %. */
  function businessUseEdit(p: RtProposal): { ok: true; edit: Record<string, unknown> } | { ok: false } {
    if (p.extracted.doc_type === "sales_invoice" || p.mileage_claim) return { ok: true, edit: {} };
    const raw = (businessUse[p.id] ?? String(p.business_use_percent ?? 100)).trim();
    if (!/^\d{1,3}$/.test(raw)) return { ok: false };
    const percent = Number(raw);
    if (percent < 0 || percent > 100) return { ok: false };
    return { ok: true, edit: percent === 100 ? {} : { business_use_percent: percent } };
  }

  function approve(p: RtProposal, sheetEdits?: Record<string, unknown>) {
    const next = neighbour([p.id]);
    return run(p.id, async () => {
      const always = rememberable && (remember[p.id] ?? false);
      const tick = asksVatStatus(p) && notRegistered[p.id] ? { [NOT_VAT_REGISTERED]: true } : {};
      const use = businessUseEdit(p);
      if (!use.ok) {
        onError("Business use is a whole percent from 0 to 100.");
        return;
      }
      const merged = { ...(approveEdits?.(p) ?? {}), ...tick, ...use.edit, ...(sheetEdits ?? {}) };
      const edits = Object.keys(merged).length ? merged : undefined;
      const handle = await adapter.approve(p, { remember: always, edits });
      const sale = p.extracted.doc_type === "sales_invoice";
      const learnt = NOT_VAT_REGISTERED in merged ? ` · ${p.extracted.supplier_name} remembered as not VAT-registered` : "";
      const done = (!always
        ? "Approved · posted to your books"
        : sale || p.mileage_claim
          ? `Approved · posted to your books (Autopilot rules are for ${sale ? "purchases" : "receipts"} only)`
          : `Approved · Autopilot will do this for ${p.extracted.supplier_name} next time`) + learnt;
      setHistory((h) => [...h, { kind: "approve", ids: [p.id], what: label(p), handles: handle ? [handle] : [] }]);
      setEditing(null);
      onNote(`${done} · U to undo`);
      setFocusNext(next);
    });
  }

  function reject(p: RtProposal) {
    const next = neighbour([p.id]);
    setRejecting(null);
    return run(p.id, async () => {
      await adapter.reject(p);
      setHistory((h) => [...h, { kind: "reject", ids: [p.id], what: label(p), handles: [], rejected: p }]);
      onNote(adapter.unreject ? "Rejected · U to undo" : "Rejected · the document is parked in 02 Needs a look");
      setFocusNext(next);
    });
  }

  function approveMatches() {
    const list = matches;
    const next = neighbour(list.map((p) => p.id));
    setBulk(false);
    return run("bulk", async () => {
      const handles: H[] = [];
      const done: string[] = [];
      const failed: string[] = [];
      for (const [i, p] of list.entries()) {
        onNote(`Approving ${i + 1} of ${list.length}: ${label(p)}…`);
        try {
          const h = await adapter.approve(p, { edits: ruleEdits(p, ruleFor.get(p.id)!) }); // a normal POST …/approve each
          if (h) handles.push(h);
          done.push(p.id);
        } catch (e) {
          failed.push(`${label(p)}: ${(e as Error).message}`);
        }
      }
      if (done.length)
        setHistory((h) => [...h, { kind: "approve", ids: done, what: `${done.length} rule match${done.length === 1 ? "" : "es"}`, handles }]);
      onNote(`Approved ${done.length} of ${list.length} rule matches · posted to your books${done.length ? " · U to undo" : ""}`);
      if (failed.length) onError(`Not approved: ${failed.join(" · ")}`);
      setFocusNext(next);
    });
  }

  function undo() {
    const last = history[history.length - 1];
    if (!last) return onNote("Nothing to undo yet.");
    if (last.kind === "reject" && !adapter.unreject) {
      setHistory((h) => h.slice(0, -1));
      return onNote(`A rejection can't be undone here: ${last.what} is in 02 Needs a look. Move it back to 00 Inbox and scan to see it again.`);
    }
    return run("undo", async () => {
      // The runtime's correction note, when an undone entry's VAT period was already submitted.
      let correction: string | null = null;
      if (last.kind === "reject") await adapter.unreject!(last.rejected!);
      else {
        const left = [...last.handles];
        try {
          while (left.length) {
            const note = await adapter.undo(left[0]);
            if (typeof note === "string" && note) correction ??= note;
            left.shift();
          }
        } catch (e) {
          // Keep only what is still posted, so pressing U again never reverses an entry twice.
          setHistory((h) => [...h.slice(0, -1), { ...last, handles: left }]);
          throw e;
        }
      }
      setHistory((h) => h.slice(0, -1));
      // Undo takes the tick back on the card, matching the runtime (forget_from_undo).
      setNotRegistered((r) => {
        const next = { ...r };
        for (const id of last.ids) delete next[id];
        return next;
      });
      onNote(
        last.kind === "reject"
          ? `Undone · ${last.what} is back in Review`
          : correction
            ? `${correction} ${last.what} is back in Review.`
            : `Undone · ${last.what}: a reversing entry was added; it is back in Review`,
      );
      setFocusNext(last.ids[0]);
    });
  }

  const activeItem = items.find((p) => p.id === active) ?? null;
  const modalOpen = editing !== null || rejecting !== null || bulk;

  // J/K move, A approve, E edit, R reject (confirmed), U undo. Ignored while typing or in a dialog.
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  useEffect(() => {
    if (busy !== null || !undoQueued.current) return;
    undoQueued.current = false;
    void undo();
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps -- undo reads this render's history
  useEffect(() => {
    keys.current = (e) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target) || modalOpen) return;
      const k = e.key.toLowerCase();
      if (!["j", "k", "a", "e", "r", "u"].includes(k)) return;
      e.preventDefault();
      if (k === "u") {
        // The note says "U to undo" before the live reload (afterDecision) clears busy: keep the press, run it then.
        if (busy !== null) undoQueued.current = true;
        else undo();
        return;
      }
      if (k === "j" || k === "k") {
        if (!items.length) return;
        const at = items.findIndex((p) => p.id === active);
        const to = at < 0 ? 0 : Math.min(items.length - 1, Math.max(0, at + (k === "j" ? 1 : -1)));
        return setFocusNext(items[to].id);
      }
      if (!activeItem) return onNote("Press J to choose a card first.");
      if (busy !== null) return;
      if (k === "a") return void approve(activeItem);
      if (k === "r") return setRejecting(activeItem.id);
      if (activeItem.mileage_claim) return onNote("A mileage claim is calculated by code: change the mileage log on Vehicles instead.");
      setEditing(activeItem.id);
    };
  });
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    document.addEventListener("keydown", on);
    return () => document.removeEventListener("keydown", on);
  }, []);

  const editItem = items.find((p) => p.id === editing);
  const rejectItem = items.find((p) => p.id === rejecting);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 ref={top} tabIndex={-1} className="text-[17px] font-extrabold outline-none">
          {items.length ? `${items.length} waiting for you` : "Nothing waiting"}
          <span className="sr-only">. Keyboard: J and K move between cards, A approves, E edits, R rejects, U undoes the last decision.</span>
        </h2>
        <p aria-hidden="true" className="hidden text-[13px] text-muted sm:block">
          <kbd className="kbd">J</kbd>/<kbd className="kbd">K</kbd> move · <kbd className="kbd">A</kbd> approve · <kbd className="kbd">E</kbd> edit ·{" "}
          <kbd className="kbd">R</kbd> reject · <kbd className="kbd">U</kbd> undo
        </p>
      </div>

      {matches.length > 1 && (
        <div className="flex flex-col gap-3 rounded-2xl border border-teal bg-teal-tint p-4 text-teal-dark sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[15px]">
            <strong>{matches.length} proposals match rules you saved</strong> and pass every check. Autopilot is at L1, so they wait for you.
          </p>
          <button type="button" disabled={busy !== null} onClick={() => setBulk(true)} className={`${primary} shrink-0`}>
            Approve all {matches.length} rule matches
          </button>
        </div>
      )}

      {items.map((p) => {
        const ui = toUi(p);
        const rule = ruleFor.get(p.id);
        const covered = new Set(p.checks.filter((c) => !c.ok).map((c) => c.message));
        const extraReasons = p.reasons.map(plainReason).filter((r) => !covered.has(r));
        const apReasons = (p.autopilot && !p.autopilot.auto_approve ? p.autopilot.reasons : []).filter((r) => !QUIET.has(r)).map(plainAutopilot);
        const working = busy === p.id;
        return (
          <ProposalCard
            key={p.id}
            proposal={ui}
            active={active === p.id}
            onFocus={() => active !== p.id && setActive(p.id)}
            cardRef={(el) => {
              if (el) cards.current.set(p.id, el);
              else cards.current.delete(p.id);
            }}
            media={<ReviewImage source={sources.get(p.id) ?? null} crop={p.crop} label={label(p)} />}
            remember={remember[p.id] ?? false}
            onRememberChange={rememberable ? (v) => setRemember((r) => ({ ...r, [p.id]: v })) : undefined}
            notices={
              (p.status === "needs_a_look" || rule || apReasons.length > 0) && (
                <>
                  {p.status === "needs_a_look" && (
                    <p className="rounded-xl border border-warn-border bg-warn-bg px-4 py-2 text-sm text-warn-ink">
                      <strong>Needs a look.</strong> {extraReasons.length ? extraReasons.join(" · ") : "Nothing has been posted. Check the lines below, then edit, approve or reject."}
                    </p>
                  )}
                  {rule && (
                    <div className="flex flex-col gap-2 rounded-xl bg-teal-tint px-4 py-3 text-sm text-teal-dark">
                      <p>
                        <strong>Matches your Autopilot rule for {rule.supplier_name || rule.supplier_key}</strong>: {rule.category}, VAT {rule.vat_code ?? "none"}, usual{" "}
                        {gbp(rule.typical_gross_pence / 100)}. At L1 it waits for you.
                      </p>
                      {matches.length > 1 && (
                        <button type="button" disabled={busy !== null} onClick={() => setBulk(true)} className={`${secondary} self-start border-teal text-teal-dark`}>
                          Approve all {matches.length} rule matches
                        </button>
                      )}
                    </div>
                  )}
                  {apReasons.length > 0 && (
                    <p className="rounded-xl bg-ground px-4 py-2 text-sm text-muted">
                      <strong>Autopilot left this for you:</strong> {apReasons.join(" · ")}
                    </p>
                  )}
                </>
              )
            }
            actions={
              <>
                {asksVatStatus(p) && (
                  <div className="flex min-h-11 items-center gap-3 rounded-xl border border-warn-border bg-warn-bg px-4 py-2 text-[15px] font-semibold text-warn-ink">
                    <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                      <input
                        type="checkbox"
                        className="h-5 w-5 shrink-0 accent-teal"
                        checked={notRegistered[p.id] ?? false}
                        onChange={(e) => setNotRegistered((r) => ({ ...r, [p.id]: e.target.checked }))}
                      />
                      <span>
                        {p.extracted.supplier_name} isn&apos;t VAT-registered
                        <span className="block text-[13px] font-medium">Approving remembers this, so their receipts aren&apos;t questioned again</span>
                      </span>
                    </label>
                    <VatQuestionExplain supplier={p.extracted.supplier_name} />
                  </div>
                )}
                {!p.mileage_claim && p.extracted.doc_type !== "sales_invoice" && (
                  <label className="flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 text-[15px] font-semibold">
                    <span>Business use %</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      inputMode="numeric"
                      value={businessUse[p.id] ?? String(p.business_use_percent ?? 100)}
                      onChange={(e) => setBusinessUse((b) => ({ ...b, [p.id]: e.target.value }))}
                      aria-label={`Business use percent for ${label(p)}`}
                      className="h-11 w-24 rounded-xl border border-border bg-white px-3 font-bold tabular-nums"
                    />
                    <span className="text-[13px] font-medium text-muted">Only this share is claimed; the rest is personal.</span>
                  </label>
                )}
                {/* Never wraps: three short buttons fit a 390 px phone. */}
                <div className="flex flex-nowrap gap-2">
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => approve(p)}
                    aria-label={`Approve ${label(p)} and post to books`}
                    aria-keyshortcuts="A"
                    className={`${primary} flex-1 sm:flex-none`}
                  >
                    {working && !editing ? "Working…" : (
                      <>
                        Approve<span className="hidden sm:inline"> (post to books)</span>
                      </>
                    )}
                  </button>
                  {!p.mileage_claim && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => setEditing(p.id)}
                      aria-label={`Edit ${label(p)} before approving`}
                      aria-keyshortcuts="E"
                      className={secondary}
                    >
                      Edit
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => setRejecting(p.id)}
                    aria-label={`Reject ${label(p)}`}
                    aria-keyshortcuts="R"
                    className={secondary}
                  >
                    Reject
                  </button>
                </div>
                {extras?.(p)}
                <QueryThisLink kind="proposal" refId={p.id} label={label(p)} />
              </>
            }
          />
        );
      })}

      {editItem && (
        <EditSheet
          proposal={editItem}
          busy={busy === editItem.id}
          onCancel={() => setEditing(null)}
          onSave={(edits) => approve(editItem, edits)}
        />
      )}
      {rejectItem && (
        <Modal label={`Reject ${label(rejectItem)}?`} onClose={() => setRejecting(null)}>
          <h2 className="text-lg font-extrabold tracking-tight">Reject {label(rejectItem)}?</h2>
          <p className="mt-2 text-[15px] leading-7 text-muted">
            {adapter.unreject
              ? "Nothing is posted. U brings it back."
              : "Nothing is posted. The document moves to 02 Needs a look. This can't be undone from Review."}
          </p>
          <div className="mt-5 flex flex-nowrap gap-2">
            <button type="button" autoFocus onClick={() => reject(rejectItem)} className={`${btn} flex-1 bg-warn-ink text-white`}>
              Reject
            </button>
            <button type="button" onClick={() => setRejecting(null)} className={secondary}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
      {bulk && matches.length > 0 && (
        <Modal label={`Approve all ${matches.length} rule matches?`} onClose={() => setBulk(false)}>
          <h2 className="text-lg font-extrabold tracking-tight">Approve all {matches.length} rule matches?</h2>
          <p className="mt-2 text-[15px] leading-7 text-muted">
            Each is posted to your books exactly as if you pressed Approve on it, with the category and account from your rule. Every one can be undone.
          </p>
          <ul className="mt-3 divide-y divide-border rounded-xl border border-border text-[15px]">
            {matches.map((p) => (
              <li key={p.id} className="flex justify-between gap-3 px-4 py-2">
                <span className="min-w-0 truncate">{p.extracted.supplier_name}</span>
                <span className="shrink-0 font-bold">{gbp(p.extracted.gross_total)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-nowrap gap-2">
            <button type="button" autoFocus onClick={approveMatches} className={`${primary} flex-1`}>
              Approve {matches.length}
            </button>
            <button type="button" onClick={() => setBulk(false)} className={secondary}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
