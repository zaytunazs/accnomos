"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { accountKind, getToken, mailScopesFor, storageScopesFor } from "@/lib/msal";
import { useAccount } from "@/components/jobs/useAccount";
import { clearTriage, setTriageOn, triageOn } from "@/lib/triage";

/** Settings › Automation › Inbox triage: Home summarises the week's business email. Reads previews only. */
export default function InboxTriageSetting() {
  const account = useAccount();
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => setOn(triageOn()));
  }, []);

  async function toggle() {
    if (on) {
      setTriageOn(false);
      clearTriage();
      setOn(false);
      setNote("Inbox triage is off. Accnomos will not read your mail for it.");
      return;
    }
    if (!account) return setNote("Connect your Microsoft account first.");
    setTriageOn(true); // saved first: consent may redirect away and back
    setOn(true);
    setBusy(true);
    try {
      await getToken([...storageScopesFor(account), ...mailScopesFor(accountKind(account))]);
      setNote("Inbox triage is on. See it on Home.");
    } catch (e) {
      const msg = (e as Error).message;
      if (msg !== "redirecting for consent") {
        setTriageOn(false);
        setOn(false);
        setNote(`Could not get permission to read mail: ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div>
        <p className="text-[15px] font-bold text-ink">Inbox triage</p>
        <p className="mt-1 text-sm text-muted">
          Home lists the last 7 days of email from customers, suppliers, HMRC and your accountant: a one-line summary, a
          suggested reply and the to-dos in it. Only the sender, subject and first 255 characters of each email are read
          and sent to your AI.
          Replies become Outlook drafts when you ask (Accnomos asks for permission to write drafts then); you send them
          yourself. <Link href="/" className="font-bold text-teal-dark">Open Home</Link>
        </p>
        {!account && <p className="mt-2 text-sm text-muted">Sign in with Microsoft to use this.</p>}
        {note && <p role="status" className="mt-2 text-sm font-bold text-teal-dark">{note}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Inbox triage"
        onClick={toggle}
        disabled={busy || (!on && !account)}
        className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-60 ${on ? "bg-teal" : "bg-border"}`}
      >
        <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
      </button>
    </div>
  );
}
