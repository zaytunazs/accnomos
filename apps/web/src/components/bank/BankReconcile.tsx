"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { money } from "@/components/bank/LiveBank";
import { runtime, ukDate, type RtAiSuggestion, type RtBankLine, type RtReconcileRow } from "@/lib/runtime";

export interface RulePrefillFrom {
  lineId: string;
  account?: string;
  vat_code?: string | null;
  contact?: string | null;
  job_id?: string | null;
}

function Coding({ account, vatCode, contact }: { account: string; vatCode: string | null; contact: string | null }) {
  return (
    <span className="text-sm">
      Code to <strong>{account}</strong>
      {vatCode ? ` (VAT ${vatCode})` : ""}
      {contact ? ` · ${contact}` : ""}
    </span>
  );
}

/** Reconcile: every open line with a suggestion, exact first, then bank rule, then the AI. You approve each. */
export default function BankReconcile({ account, lines, onChanged, onCreateRule }: {
  account: AccountInfo;
  /** Every bank line, for the descriptions behind reconcile rows. */
  lines: RtBankLine[];
  onChanged: () => void;
  onCreateRule: (from: RulePrefillFrom) => void;
}) {
  const [rows, setRows] = useState<RtReconcileRow[] | null>(null);
  const [aiByLine, setAiByLine] = useState<Record<string, RtAiSuggestion | null>>({});
  const [aiBusy, setAiBusy] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const byId = new Map(lines.map((l) => [l.id, l]));

  const reload = useCallback(async () => {
    try {
      setRows(await runtime.bank.reconcile(account));
    } catch (e) {
      setNote((e as Error).message);
    }
  }, [account]);

  useEffect(() => {
    (async () => {
      await reload();
    })().catch(() => null);
  }, [reload]);

  async function approve(lineId: string, kind: "exact" | "rule" | "ai", label: string) {
    setBusy(`${lineId}:${kind}`);
    setNote(null);
    try {
      const ai = kind === "ai" ? aiByLine[lineId] ?? null : null;
      const r = await runtime.bank.reconcileApprove(account, lineId, kind, ai);
      setNote(
        r.event_id
          ? `Posted ${label} through Review approval.`
          : `Matched ${label}.`,
      );
      onChanged();
      await reload();
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function askAi(lineId: string) {
    setAiBusy(lineId);
    try {
      const suggestion = await runtime.bank.aiSuggestion(account, lineId);
      setAiByLine((m) => ({ ...m, [lineId]: suggestion }));
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setAiBusy(null);
    }
  }

  if (rows === null) {
    return <p className="py-6 text-center text-sm font-semibold text-muted">Checking each open line…</p>;
  }
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm font-semibold text-muted">Nothing to reconcile: no open line matches an invoice, a rule or the AI.</p>;
  }
  const exacts = rows.filter((r) => r.exact);

  return (
    <div className="flex flex-col gap-3">
      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">{note}</p>
      )}
      {exacts.length > 1 && (
        <div>
          <button
            type="button"
            disabled={busy !== null}
            onClick={async () => {
              setBusy("all");
              try {
                for (const r of exacts) await runtime.bank.reconcileApprove(account, r.line_id, "exact");
                setNote(`Confirmed ${exacts.length} exact ${exacts.length === 1 ? "match" : "matches"}.`);
                onChanged();
                await reload();
              } catch (e) {
                setNote((e as Error).message);
              } finally {
                setBusy(null);
              }
            }}
            className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
          >
            {busy === "all" ? "Confirming…" : `Confirm all ${exacts.length} exact matches`}
          </button>
        </div>
      )}
      <ul className="flex flex-col gap-3">
        {rows.map((r) => {
          const line = byId.get(r.line_id);
          if (!line) return null;
          const label = `${line.description} ${money(line.amount_pence)}`;
          const ai = aiByLine[r.line_id] ?? null;
          return (
            <li key={r.line_id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
              <div className="flex items-baseline justify-between gap-3">
                <p className="min-w-0 font-semibold">{line.description || "—"}</p>
                <p className="shrink-0 font-bold tabular-nums">{money(line.amount_pence)}</p>
              </div>
              <p className="text-[13px] font-medium text-muted">
                {ukDate(line.date)}
                {line.reference ? ` · ${line.reference}` : ""}
              </p>
              {r.exact && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl bg-teal-tint p-3">
                  <span className="rounded-full bg-teal px-2 py-0.5 text-[12px] font-bold text-white">Exact</span>
                  <span className="text-sm">{r.exact.reasons.join(" · ")}</span>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void approve(r.line_id, "exact", label)}
                    aria-label={`Approve exact match: ${label}`}
                    className="h-10 rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                  >
                    {busy === `${r.line_id}:exact` ? "…" : "Approve"}
                  </button>
                </div>
              )}
              {r.rule && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl bg-ground p-3">
                  <span className="rounded-full border border-border bg-white px-2 py-0.5 text-[12px] font-bold">Bank rule{r.rule.rule_name ? ` · ${r.rule.rule_name}` : ""}</span>
                  <Coding account={r.rule.account} vatCode={r.rule.vat_code} contact={r.rule.contact} />
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void approve(r.line_id, "rule", label)}
                    aria-label={`Approve bank rule: ${label}`}
                    className="h-10 rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                  >
                    {busy === `${r.line_id}:rule` ? "…" : "Approve"}
                  </button>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border p-3">
                <span className="rounded-full border border-warn-border bg-warn-bg px-2 py-0.5 text-[12px] font-bold text-warn-ink">AI</span>
                {ai ? (
                  <>
                    <Coding account={ai.account} vatCode={ai.vat_code} contact={ai.contact} />
                    <span className="text-[13px] text-muted">{ai.by}{ai.reason ? ` · ${ai.reason}` : ""}</span>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void approve(r.line_id, "ai", label)}
                      aria-label={`Approve AI suggestion: ${label}`}
                      className="h-10 rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
                    >
                      {busy === `${r.line_id}:ai` ? "…" : "Approve"}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    disabled={aiBusy !== null || busy !== null}
                    onClick={() => void askAi(r.line_id)}
                    aria-label={`Suggest with AI: ${label}`}
                    className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-bold hover:bg-ground disabled:opacity-60"
                  >
                    {aiBusy === r.line_id ? "Asking…" : "Suggest with AI"}
                  </button>
                )}
              </div>
              <div>
                <button
                  type="button"
                  onClick={() => onCreateRule({
                    lineId: r.line_id,
                    account: r.rule?.account ?? ai?.account,
                    vat_code: r.rule?.vat_code ?? ai?.vat_code,
                    contact: r.rule?.contact ?? ai?.contact,
                    job_id: r.rule?.job_id,
                  })}
                  aria-label={`Create rule from this: ${label}`}
                  className="text-[13px] font-bold text-teal-dark underline underline-offset-2"
                >
                  Create rule from this
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
