"use client";

import Link from "next/link";
import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import type { RtProposedAction } from "@/lib/runtime";
import { categoryLabel, supportDesk, type Consent, type Ticket } from "@/lib/support-api";
import { errorText } from "@/components/jobs/useAccount";

/**
 * The assistant's `create_support_ticket` card. Like every proposed action it does nothing until the user taps: here
 * **Create ticket**, after choosing what to attach. Nothing financial is sent unless "Include financial details" is
 * ticked. The runtime checks the card's signature, so the summary it files is the one shown.
 */
export default function TicketCard({
  action,
  account,
  conversation = [],
  onCreated,
}: {
  action: RtProposedAction;
  account: AccountInfo;
  /** The assistant thread as shown, sent only with "Include financial details". */
  conversation?: { role: "user" | "assistant"; text: string }[];
  onCreated?: (t: Ticket) => void;
}) {
  const p = action.preview as { subject?: string; category?: string; description?: string; steps?: string[]; page?: string | null };
  const [consent, setConsent] = useState<Consent>({ attach_errors: true, include_paypal: p.category === "paypal", include_financial: false });
  const [details, setDetails] = useState("");
  const [state, setState] = useState<{ step: "ready" | "working" | "dismissed" } | { step: "done"; ticket: Ticket; created: boolean } | { step: "error"; message: string }>({
    step: "ready",
  });
  const tick = (k: keyof Omit<Consent, "conversation">) => setConsent((c) => ({ ...c, [k]: !c[k] }));

  async function create() {
    setState({ step: "working" });
    try {
      const out = await supportDesk.fromCard(account, action, { ...consent, conversation }, details);
      setState({ step: "done", ticket: out.ticket, created: out.created });
      onCreated?.(out.ticket);
    } catch (e) {
      setState({ step: "error", message: errorText(e) });
    }
  }

  if (state.step === "dismissed")
    return (
      <p className="text-[14px] text-muted" role="status">
        No ticket made. Nothing was sent.
      </p>
    );
  return (
    <article className="rounded-2xl border-2 border-teal bg-white p-5" aria-label="Proposed: Support ticket" data-ticket-card="">
      <p className="mb-2 text-[12px] font-bold uppercase tracking-wide text-teal-dark">Proposed · Support ticket · needs your OK</p>
      <dl className="text-[14px] leading-6">
        <div className="flex gap-3 py-1">
          <dt className="w-24 shrink-0 text-muted">Summary</dt>
          <dd className="min-w-0 flex-1 font-bold">{p.subject}</dd>
        </div>
        <div className="flex gap-3 py-1">
          <dt className="w-24 shrink-0 text-muted">Category</dt>
          <dd className="min-w-0 flex-1">{categoryLabel(p.category ?? "other")}</dd>
        </div>
        {p.steps && p.steps.length > 0 && (
          <div className="flex gap-3 py-1">
            <dt className="w-24 shrink-0 text-muted">So far</dt>
            <dd className="min-w-0 flex-1">
              <ul className="ml-4 list-disc">
                {p.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        {p.page && (
          <div className="flex gap-3 py-1">
            <dt className="w-24 shrink-0 text-muted">Page</dt>
            <dd className="min-w-0 flex-1">{p.page}</dd>
          </div>
        )}
      </dl>
      {state.step === "done" ? (
        <div className="mt-4 rounded-xl bg-teal-tint p-3 text-[14px] text-teal-dark" role="status">
          ✓ {state.created ? "Created" : "Already created:"} ticket <strong>{state.ticket.number}</strong>.{" "}
          <Link href={`/support?ticket=${state.ticket.id}`} className="font-bold underline underline-offset-2">
            Open it on Support
          </Link>
          . Replies appear there.
        </div>
      ) : (
        <>
          <label className="mt-3 block text-[14px]">
            <span className="font-bold">Anything to add?</span> <span className="text-muted">(optional)</span>
            <textarea value={details} onChange={(e) => setDetails(e.target.value)} rows={2} maxLength={5000} className="mt-1 w-full rounded-xl border border-border p-2 text-[14px]" />
          </label>
          <fieldset className="mt-3 flex flex-col gap-1.5 text-[14px]">
            <legend className="font-bold">What to attach</legend>
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={consent.attach_errors} onChange={() => tick("attach_errors")} className="mt-1" />
              <span>Attach recent errors (the last error messages this tab saw; no figures)</span>
            </label>
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={consent.include_paypal} onChange={() => tick("include_paypal")} className="mt-1" />
              <span>Include PayPal details (connected or not, last sync, the last PayPal problem)</span>
            </label>
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={consent.include_financial} onChange={() => tick("include_financial")} className="mt-1" />
              <span>Include financial details (amounts in your words and this conversation). Off: amounts are masked.</span>
            </label>
          </fieldset>
          {state.step === "error" && (
            <p className="mt-2 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink" role="alert">
              {state.message}
            </p>
          )}
          <p className="mt-3 text-[14px] font-bold">Create this support ticket?</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={() => void create()} disabled={state.step === "working"} className="flex h-10 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50">
              {state.step === "working" ? "Creating…" : "Create ticket"}
            </button>
            <button type="button" onClick={() => setState({ step: "dismissed" })} disabled={state.step === "working"} className="flex h-10 items-center rounded-xl px-4 text-[15px] font-bold text-muted hover:bg-ground disabled:opacity-50">
              Not now
            </button>
          </div>
        </>
      )}
    </article>
  );
}
