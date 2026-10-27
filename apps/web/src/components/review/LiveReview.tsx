"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import ProposalCard from "@/components/review/ProposalCard";
import UploadToInbox from "@/components/review/UploadToInbox";
import { getMsal, msalConfigured } from "@/lib/msal";
import { gbp, runtime, ukDate, type RtProposal } from "@/lib/runtime";
import type { Proposal as UiProposal } from "@/lib/sample-review";

type Mode = "checking" | "demo" | "live";

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
  model.startsWith("baseten:") ? "Muse Spark Open" : model.startsWith("meta:") ? "Muse Spark" : "Glimmer 30B";

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
    verifierNote: `Verifier disagrees on ${diffs.length} of ${fields.length} fields — ${verifierName(v.model)}. Check the document and choose.`,
    verifierTone: "differ",
    verifierDiffs: diffs,
  };
}

/** Map a runtime proposal onto the card's display model (strings only, plain English). */
export function toUi(p: RtProposal): UiProposal {
  const x = p.extracted;
  const local = p.model.startsWith("local:");
  const lines = p.journal_draft.map((l) => {
    const amt = gbp((l.debit_pence || l.credit_pence) / 100);
    const isVat = l.account.includes("2200");
    const isSettle = l.credit_pence > 0 && !isVat && x.doc_type !== "sales_invoice";
    const label = isVat ? "VAT to reclaim" : isSettle ? `Paid from ${x.payment_method === "cash" ? "cash" : "business card"}` : l.account.replace(/^\d{4}\s/, "");
    const meaning = isVat ? "Goes to Box 4" : isSettle ? "Will match a bank line" : `Expense, ${codeMeaning[l.vat_code ?? ""] ?? "VAT as shown"}`;
    return { account: `${label} ${amt}`, amount: amt, meaning };
  });
  const fails = p.checks.filter((c) => !c.ok);
  const why = fails.length
    ? `Why it's flagged: ${fails.map((c) => c.message).join("; ")}.`
    : `Why: ${x.lines.length} line${x.lines.length === 1 ? "" : "s"}, totals add up (${x.net_total.toFixed(2)} + ${x.vat_total.toFixed(2)} = ${x.gross_total.toFixed(2)}); category "${x.category_guess}". — Checker, code`;
  return {
    id: p.id,
    supplier: x.supplier_name,
    total: gbp(x.gross_total),
    confidence: `Confidence ${Math.round(x.confidence * 100)}%`,
    source: local ? "Read by Glimmer 30B on your machine" : "Read by Muse Spark",
    date: ukDate(x.date),
    vatNumber: x.supplier_vat_number ? `${x.supplier_vat_number} ✓` : "none shown",
    net: gbp(x.net_total),
    vat: gbp(x.vat_total),
    paidBy: x.card_last4 ? `Card ending ${x.card_last4}` : (x.payment_method ?? "—"),
    lines,
    reviewerNote: why,
    ...verifierView(p),
  };
}

export default function LiveReview({ fallback }: { fallback: React.ReactNode }) {
  const [mode, setMode] = useState<Mode>("checking");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [items, setItems] = useState<RtProposal[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async (acct: AccountInfo) => {
    const [proposed, flagged] = await Promise.all([runtime.proposals(acct, "proposed"), runtime.proposals(acct, "needs_a_look")]);
    setItems([...proposed, ...flagged]);
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
    try {
      await fn();
      setNote(done);
      if (account) await load(account);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function scan() {
    if (!account) return;
    setBusy("scan");
    try {
      const r = await runtime.scan(account);
      const n = r.proposals.length;
      const errs = r.errors.map((e) => `${e.path.split("/").pop()}: ${e.error}`).join(" · ");
      setNote(`${n} new proposal${n === 1 ? "" : "s"}${errs ? ` · could not read: ${errs}` : ""}`);
      await load(account);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (mode === "checking") return <p className="text-sm text-muted">Loading your proposals…</p>;
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
        <button type="button" onClick={scan} disabled={busy !== null} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60">
          {busy === "scan" ? "Reading your Inbox…" : "Scan 00 Inbox now"}
        </button>
        <UploadToInbox account={account!} onDone={() => setNote("Added to your Inbox.")} />
        <span className="text-sm text-muted">{items.length} waiting · or drop files into OneDrive › Apps › Accnomos › 00 Inbox</span>
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm text-teal-dark">{note}</p>}
      {items.length === 0 && <p className="rounded-2xl border border-border bg-white p-6 text-muted">Nothing to review. Your books are up to date.</p>}
      {items.map((p) => (
        <div key={p.id} className="flex flex-col gap-2">
          {p.status === "needs_a_look" && (
            <div className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
              <strong>Needs a look.</strong> {p.reasons.join(" · ")}
            </div>
          )}
          <ProposalCard proposal={toUi(p)} />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => act(p.id, () => runtime.approve(account!, p.id, {}), "Approved · posted to your books")}
              className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60"
            >
              {busy === p.id ? "Working…" : "Approve (post to books)"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => act(p.id, () => runtime.approve(account!, p.id, { always: true }), "Approved · rule saved for this supplier")}
              className="h-11 rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
            >
              Approve + always do this
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => act(p.id, () => runtime.reject(account!, p.id, "rejected by user"), "Rejected")}
              className="h-11 rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
