"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { mailboxTokenSilent } from "@/lib/msal";
import { trackScanJob } from "@/lib/scan-jobs";
import { runtime, type RtMailbox, type RtMailScan } from "@/lib/runtime";

/** Fired after a check, so Settings › Email intake re-reads each mailbox's last check. */
export const MAILBOXES_CHECKED = "accnomos:mailboxes-checked";

export interface MailboxCheck {
  mailbox: string; // address ("" when the runtime does not know the signed-in address)
  kind: RtMailbox["kind"];
  result?: RtMailScan;
  needsSignIn?: boolean; // no token could be had without asking the user
  error?: string;
}

export const KIND_LABEL: Record<RtMailbox["kind"], string> = {
  primary: "Signed-in account",
  microsoft: "Microsoft account",
  shared: "Shared mailbox",
};

/**
 * Outlook intake over every mailbox: the signed-in one first, then each linked one this browser can get a token for
 * without a prompt, one request each (its token travels alone, in X-Mailbox-Token). One after another, so a file
 * the first mailbox copied into 00 Inbox is a duplicate for the next. A mailbox that needs a sign-in is reported,
 * not skipped silently; one that fails does not stop the others.
 */
export async function checkAllMailboxes(
  account: AccountInfo,
  options: { since_days?: number; dry_run?: boolean },
): Promise<MailboxCheck[]> {
  const out: MailboxCheck[] = [];
  // A real check also starts reading what it saved (a background scan job each, followed by lib/scan-jobs.ts).
  const body = { ...options, read_now: !options.dry_run };
  const primary = await runtime.mailScan(account, body);
  if (primary.scan_job_id) trackScanJob(primary.scan_job_id);
  out.push({ mailbox: primary.mailbox || account.username, kind: "primary", result: primary });
  let linked: RtMailbox[] = [];
  try {
    linked = (await runtime.mailboxes(account)).filter((m) => m.kind !== "primary");
  } catch {
    return out; // the signed-in mailbox was read; the list can be fetched next time
  }
  for (const box of linked) {
    const kind = box.kind === "shared" ? "shared" : "microsoft";
    const token = await mailboxTokenSilent(kind, box.address);
    if (!token) {
      out.push({ mailbox: box.address, kind: box.kind, needsSignIn: true });
      continue;
    }
    try {
      const result = await runtime.mailScanLinked(account, box.id, token, body);
      if (result.scan_job_id) trackScanJob(result.scan_job_id);
      out.push({ mailbox: box.address, kind: box.kind, result });
    } catch (e) {
      out.push({ mailbox: box.address, kind: box.kind, error: (e as Error).message });
    }
  }
  try {
    window.dispatchEvent(new Event(MAILBOXES_CHECKED));
  } catch {
    /* no window */
  }
  return out;
}

/** "screwfix.com, bills@uber.com" → ["screwfix.com", "bills@uber.com"]. */
export function parseSenders(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
