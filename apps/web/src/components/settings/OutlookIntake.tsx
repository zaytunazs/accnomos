"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import Explain from "@/components/Explain";
import { accountKind, getMsal, getToken, mailScopesFor, msalConfigured, storageScopesFor } from "@/lib/msal";
import { intakeOn, recordInboxCheck, setIntakeOn } from "@/lib/intake";
import { checkAllMailboxes, type MailboxCheck } from "@/lib/mailboxes";
import type { RtMailScan } from "@/lib/runtime";

/** Several mailboxes' results as one: what the summary line and the file chips show. */
function combine(checks: MailboxCheck[]): RtMailScan {
  const done = checks.flatMap((c) => (c.result ? [c.result] : []));
  return {
    scanned: done.reduce((n, r) => n + r.scanned, 0),
    candidates: done.reduce((n, r) => n + r.candidates, 0),
    saved: done.flatMap((r) => r.saved),
    skipped_duplicates: done.reduce((n, r) => n + r.skipped_duplicates, 0),
    dry_run: done[0]?.dry_run ?? false,
    errors: done.flatMap((r) => r.errors),
    items: done.flatMap((r) => r.items),
  };
}

/** Settings card: copy receipts/invoices from Outlook into 00 Inbox. Reads mail only; never moves or deletes. */
export default function OutlookIntake({ card, heading }: { card: string; heading: string }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState<"consent" | "scan" | "preview" | null>(null);
  const [result, setResult] = useState<RtMailScan | null>(null);
  const [checks, setChecks] = useState<MailboxCheck[]>([]);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    queueMicrotask(() => setOn(intakeOn()));
    (async () => {
      if (!msalConfigured()) return;
      try {
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        setAccount(msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null);
      } catch {
        /* not signed in */
      }
    })();
  }, []);

  async function toggle() {
    if (on) {
      setIntakeOn(false);
      setOn(false);
      setResult(null);
      setNote("Outlook intake is off. Accnomos will not read your mail.");
      return;
    }
    if (!account) return setNote("Connect your Microsoft account first.");
    setIntakeOn(true); // saved first: consent may redirect away and back
    setOn(true);
    setBusy("consent");
    try {
      await getToken([...storageScopesFor(account), ...mailScopesFor(accountKind(account))]);
      setNote("Outlook intake is on. Accnomos can now read (not change) your mail.");
    } catch (e) {
      const msg = (e as Error).message;
      if (msg !== "redirecting for consent") {
        setIntakeOn(false);
        setOn(false);
        setNote(`Could not get permission to read mail: ${msg}`);
      }
    } finally {
      setBusy(null);
    }
  }

  async function check(dryRun: boolean) {
    if (!account) return;
    setBusy(dryRun ? "preview" : "scan");
    setNote(null);
    try {
      const all = await checkAllMailboxes(account, { since_days: 14, dry_run: dryRun });
      const r = combine(all);
      setChecks(all);
      setResult(r);
      if (!dryRun) recordInboxCheck(r.saved.length);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const n = result?.saved.length ?? 0;

  return (
    <section aria-labelledby="settings-intake" className={card}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 id="settings-intake" className={heading}>
              Outlook intake
            </h3>
            <Explain title="What Outlook intake reads and writes">
              <p>
                When you tap “Check my inbox now”, Accnomos looks at emails from the last 14
                days. Plain code — no AI — keeps files that look like receipts or invoices: PDF,
                JPEG, PNG or HEIC attachments between 10 KB and 25 MB, from a sender outside your
                own domain, with words like receipt, invoice or VAT in the subject or file name.
                HEIC photos are saved as JPEG.
              </p>
              <p>
                Receipts written in the email itself (a taxi ride, an online order, a software
                subscription) are kept too: for an email with no attachment whose subject or
                preview mentions a receipt, order or payment, the text is read and kept when a
                total or VAT line shows an amount. Newsletters and sale emails are skipped.
              </p>
              <p>
                Read: the message date, sender, subject, those attachments and those email texts.
                Written, all in your own folder: the file as
                00 Inbox/&lt;date&gt;_&lt;sender&gt;_&lt;name&gt; (an email as …_&lt;subject&gt;.eml.txt),
                a seen-list so nothing is copied twice, and a dated log.
              </p>
              <p>
                Never: sending, moving, flagging, marking as read or deleting mail, or keeping
                anything on our server. The last check time is kept only in this browser.
              </p>
            </Explain>
          </div>
          <p className="mt-1 text-sm text-muted">
            Copies receipts and invoices attached to your emails into <span className="font-bold">00 Inbox</span>.
            Mail is only read: nothing is moved, marked or deleted.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Outlook intake"
          onClick={toggle}
          disabled={busy !== null || (!on && !account)}
          className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-60 ${on ? "bg-teal" : "bg-border"}`}
        >
          <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
        </button>
      </div>

      {!account && <p className="mt-3 text-sm text-muted">Sign in with Microsoft to use this.</p>}

      {on && account && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => check(false)}
            disabled={busy !== null}
            className="h-11 whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-60"
          >
            {busy === "scan" ? "Checking your inbox…" : "Check my inbox now"}
          </button>
          <button
            type="button"
            onClick={() => check(true)}
            disabled={busy !== null}
            className="text-sm font-bold text-teal-dark underline-offset-2 hover:underline disabled:opacity-60"
          >
            {busy === "preview" ? "Looking…" : "Preview what would be imported"}
          </button>
        </div>
      )}

      {result && (
        <div role="status" className="mt-4 rounded-xl bg-ground px-4 py-3 text-sm text-ink">
          <p className="font-bold">
            {result.dry_run ? `${n} file${n === 1 ? "" : "s"} would be imported` : `${n} file${n === 1 ? "" : "s"} imported`}
            <span className="font-medium text-muted">
              {" "}· {result.scanned} email{result.scanned === 1 ? "" : "s"} with attachments in the last 14 days
              {result.skipped_duplicates ? ` · ${result.skipped_duplicates} already in your books` : ""}
            </span>
          </p>
          {n > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2">
              {result.items.map((it) => (
                <li key={`${it.mailbox ?? ""}/${it.name}`}>
                  {result.dry_run ? (
                    <span title={it.subject} className="inline-block rounded-full border border-border bg-white px-3 py-1 text-[13px] font-semibold text-muted">
                      {it.name}
                    </span>
                  ) : (
                    <Link href="/review" title={it.subject} className="inline-block rounded-full bg-teal-tint px-3 py-1 text-[13px] font-bold text-teal-dark hover:bg-teal hover:text-white">
                      {it.name}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!result.dry_run && n > 0 && (
            <p className="mt-2 text-muted">
              Reading them now: <Link href="/review" className="font-bold text-teal-dark">confirm each one&rsquo;s type on Review</Link>.
            </p>
          )}
          {checks.length > 1 && (
            <div className="mt-2 space-y-0.5 text-muted" data-testid="intake-by-mailbox">
              {checks.map((c) => (
                <p key={c.mailbox}>
                  <span className="font-semibold text-ink">{c.mailbox}</span>
                  {": "}
                  {c.result
                    ? `${c.result.saved.length} file${c.result.saved.length === 1 ? "" : "s"}` +
                      (c.result.skipped_duplicates ? `, ${c.result.skipped_duplicates} already in your books` : "")
                    : c.needsSignIn
                      ? "not read: sign in to it again under Email intake"
                      : `not read (${c.error})`}
                </p>
              ))}
            </div>
          )}
          {result.dry_run && checks.length > 1 && (
            <p className="mt-2 text-muted">
              Each mailbox is previewed on its own: a receipt sent to two of them is listed twice here but copied once.
            </p>
          )}
          {result.errors.length > 0 && (
            <p className="mt-2 text-muted">
              Could not copy: {result.errors.map((e) => `${e.attachment ?? e.message ?? "email"} (${e.error})`).join(" · ")}
            </p>
          )}
        </div>
      )}

      {note && <p role="status" className="mt-3 text-sm font-bold text-teal-dark">{note}</p>}
    </section>
  );
}
