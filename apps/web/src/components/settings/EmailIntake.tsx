"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Explain from "@/components/Explain";
import { ago } from "@/lib/intake";
import { KIND_LABEL, MAILBOXES_CHECKED, parseSenders } from "@/lib/mailboxes";
import {
  forgetExtraAccount,
  getMsal,
  getToken,
  isPersonalAccount,
  mailboxTokenSilent,
  msalConfigured,
  primaryAccount,
  SHARED_MAIL_SCOPES,
  signInExtraAccount,
} from "@/lib/msal";
import { runtime, type RtMailbox } from "@/lib/runtime";

const FOLDERS: { value: string; label: string }[] = [
  { value: "all", label: "All folders" },
  { value: "inbox", label: "Inbox" },
  { value: "archive", label: "Archive" },
];

const input = "h-10 w-full min-w-0 rounded-xl border border-border bg-white px-3 text-sm text-ink";
const smallButton =
  "h-9 shrink-0 whitespace-nowrap rounded-xl border border-border bg-white px-3 text-[13px] font-bold text-ink disabled:opacity-60";

/** Settings › Email intake: the mailboxes Outlook intake reads, each with its folder and sender lists. */
export default function EmailIntake({ card, heading }: { card: string; heading: string }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [boxes, setBoxes] = useState<RtMailbox[] | null>(null);
  const [signedIn, setSignedIn] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [sharedOpen, setSharedOpen] = useState(false);
  const [sharedAddress, setSharedAddress] = useState("");

  const load = useCallback(async (acct: AccountInfo) => {
    const list = await runtime.mailboxes(acct);
    setBoxes(list);
    const status: Record<string, boolean> = {};
    for (const b of list) {
      if (b.kind !== "primary") status[b.id] = (await mailboxTokenSilent(b.kind, b.address)) !== null;
    }
    setSignedIn(status);
  }, []);

  useEffect(() => {
    (async () => {
      if (!msalConfigured()) return;
      try {
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = primaryAccount(msal);
        if (!acct) return;
        setAccount(acct);
        await load(acct);
      } catch (e) {
        setNote((e as Error).message);
      }
    })();
  }, [load]);

  useEffect(() => {
    if (!account) return;
    const refresh = () => void load(account).catch(() => undefined);
    window.addEventListener(MAILBOXES_CHECKED, refresh);
    return () => window.removeEventListener(MAILBOXES_CHECKED, refresh);
  }, [account, load]);

  async function run(key: string, work: () => Promise<string | null>) {
    setBusy(key);
    setNote(null);
    try {
      const msg = await work();
      if (account) await load(account);
      if (msg) setNote(msg);
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function addMicrosoft() {
    return run("add-microsoft", async () => {
      if (!account) return null;
      const extra = await signInExtraAccount();
      if (extra.homeAccountId === account.homeAccountId) {
        return "That is the account you are signed in with: its mailbox is already read. Pick another account.";
      }
      await runtime.addMailbox(account, { address: extra.username, kind: "microsoft" });
      return `${extra.username} added. Accnomos can read (not change) its mail.`;
    });
  }

  function addShared() {
    return run("add-shared", async () => {
      if (!account) return null;
      const address = sharedAddress.trim();
      if (!address) return "Type the shared mailbox's address first.";
      await runtime.addMailbox(account, { address, kind: "shared" });
      setSharedAddress("");
      setSharedOpen(false);
      if ((await mailboxTokenSilent("shared", address)) === null) {
        await getToken(SHARED_MAIL_SCOPES); // asks Microsoft for Mail.Read.Shared (may leave the page and come back)
      }
      return `${address} added. It is read with your own sign-in, so you need access to it in Outlook.`;
    });
  }

  function signInAgain(box: RtMailbox) {
    return run(`signin-${box.id}`, async () => {
      if (box.kind === "shared") {
        await getToken(SHARED_MAIL_SCOPES);
        return null;
      }
      const extra = await signInExtraAccount(box.address);
      return extra.username.toLowerCase() === box.address
        ? `Signed in to ${box.address} again.`
        : `You signed in as ${extra.username}, not ${box.address}. Try again and pick ${box.address}.`;
    });
  }

  function remove(box: RtMailbox) {
    return run(`remove-${box.id}`, async () => {
      if (!account) return null;
      await runtime.removeMailbox(account, box.id);
      if (box.kind === "microsoft") await forgetExtraAccount(box.address);
      return `${box.address} removed. Files it already copied stay in your books.`;
    });
  }

  function save(box: RtMailbox, change: { folder: string; allow: string; deny: string }) {
    return run(`save-${box.id}`, async () => {
      if (!account) return null;
      await runtime.updateMailbox(account, box.id, {
        folder: change.folder,
        allow_senders: parseSenders(change.allow),
        deny_senders: parseSenders(change.deny),
      });
      return `Saved for ${box.address || "your mailbox"}.`;
    });
  }

  const personal = account ? isPersonalAccount(account) : true;

  return (
    <section aria-labelledby="settings-email-intake" id="email-intake" className={card}>
      <div className="flex items-center gap-2">
        <h3 id="settings-email-intake" className={heading}>
          Email intake
        </h3>
        <Explain title="Which mailboxes Outlook intake reads">
          <p>
            Your own mailbox is always read. You can add more: another Outlook.com or Microsoft 365
            account (you sign in to it in a pop-up, and Accnomos asks only to read its mail), or a
            shared mailbox such as accounts@ that your work account can already open in Outlook.
          </p>
          <p>
            Kept in your books (_System/mail/mailboxes.json): each address, the folder to watch,
            the sender lists and the last check. Never a password or a token: sign-ins stay in this
            browser, and each mailbox&rsquo;s token is sent only with the check of that mailbox.
          </p>
          <p>
            A receipt sent to two of your mailboxes is copied once. Each document remembers which
            mailbox it came from, on its Review card data and in the audit trail.
          </p>
        </Explain>
      </div>
      <p className="mt-1 text-sm text-muted">
        The mailboxes &ldquo;Check my inbox now&rdquo; reads, with the folder to watch and who to take receipts from.
      </p>

      {!account && <p className="mt-3 text-sm text-muted">Sign in with Microsoft to use this.</p>}

      {boxes && (
        <ul className="mt-3 flex flex-col gap-2" aria-label="Mailboxes">
          {boxes.map((box) => (
            <MailboxRow
              key={box.id}
              box={box}
              address={box.address || account?.username || ""}
              signedIn={box.kind === "primary" ? true : (signedIn[box.id] ?? false)}
              busy={busy}
              onSave={(c) => save(box, c)}
              onRemove={() => remove(box)}
              onSignIn={() => signInAgain(box)}
            />
          ))}
        </ul>
      )}

      {account && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={addMicrosoft}
            disabled={busy !== null}
            className="h-10 whitespace-nowrap rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
          >
            {busy === "add-microsoft" ? "Signing in…" : "Add Microsoft mailbox"}
          </button>
          <button
            type="button"
            onClick={() => setSharedOpen((o) => !o)}
            disabled={busy !== null || personal}
            aria-expanded={sharedOpen}
            className={smallButton + " h-10"}
          >
            Add shared mailbox
          </button>
          <button type="button" disabled className={smallButton + " h-10 text-muted"}>
            Gmail (coming soon)
          </button>
        </div>
      )}
      {account && personal && (
        <p className="mt-2 text-[13px] text-muted">
          Shared mailboxes need a work or school account: Microsoft offers that permission (Mail.Read.Shared) only there.
        </p>
      )}
      {account && (
        <p className="mt-1 text-[13px] text-muted">
          Gmail needs a Google Cloud app for Accnomos, which is not set up yet.
        </p>
      )}

      {sharedOpen && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void addShared();
          }}
        >
          <label className="min-w-0 flex-1 text-[13px] font-bold text-ink">
            Shared mailbox address
            <input
              type="email"
              value={sharedAddress}
              onChange={(e) => setSharedAddress(e.target.value)}
              placeholder="accounts@yourbusiness.co.uk"
              className={`${input} mt-1 font-normal`}
            />
          </label>
          <button type="submit" disabled={busy !== null} className={smallButton + " h-10"}>
            {busy === "add-shared" ? "Adding…" : "Add"}
          </button>
        </form>
      )}

      {note && (
        <p role="status" className="mt-3 text-sm font-bold text-teal-dark">
          {note}
        </p>
      )}
    </section>
  );
}

function MailboxRow({
  box,
  address,
  signedIn,
  busy,
  onSave,
  onRemove,
  onSignIn,
}: {
  box: RtMailbox;
  address: string;
  signedIn: boolean;
  busy: string | null;
  onSave: (c: { folder: string; allow: string; deny: string }) => void;
  onRemove: () => void;
  onSignIn: () => void;
}) {
  const known = FOLDERS.some((f) => f.value === box.folder);
  const [folderChoice, setFolderChoice] = useState(known ? box.folder : "other");
  const [folderName, setFolderName] = useState(known ? "" : box.folder);
  const [allow, setAllow] = useState(box.allow_senders.join(", "));
  const [deny, setDeny] = useState(box.deny_senders.join(", "));
  const last = box.last_scan_at
    ? `Last checked ${ago(box.last_scan_at)} · ${box.last_scan_saved ?? 0} file${box.last_scan_saved === 1 ? "" : "s"}`
    : "Not checked yet";

  return (
    <li aria-label={address} className="rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-all text-[15px] font-bold text-ink">{address}</p>
          <p className="mt-0.5 text-[13px] text-muted">
            {KIND_LABEL[box.kind]} · {last}
            {box.last_scan_error ? ` · ${box.last_scan_error}` : ""}
          </p>
          {!signedIn && (
            <p className="mt-0.5 text-[13px] font-bold text-warn-ink">
              {box.kind === "shared" ? "Needs your permission to read shared mail" : "Signed out in this browser"}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          {!signedIn && (
            <button type="button" onClick={onSignIn} disabled={busy !== null} className={smallButton}>
              {box.kind === "shared" ? "Allow" : "Sign in again"}
            </button>
          )}
          {box.kind !== "primary" && (
            <button
              type="button"
              onClick={onRemove}
              disabled={busy !== null}
              aria-label={`Remove ${address}`}
              className={smallButton}
            >
              {busy === `remove-${box.id}` ? "Removing…" : "Remove"}
            </button>
          )}
        </div>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer text-[13px] font-bold text-teal-dark">Folder and senders</summary>
        <form
          className="mt-2 grid gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onSave({ folder: folderChoice === "other" ? folderName : folderChoice, allow, deny });
          }}
        >
          <label className="text-[13px] font-bold text-ink">
            Folder to watch
            <select
              value={folderChoice}
              onChange={(e) => setFolderChoice(e.target.value)}
              className={`${input} mt-1 font-normal`}
            >
              {FOLDERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
              <option value="other">Another folder…</option>
            </select>
          </label>
          {folderChoice === "other" && (
            <label className="text-[13px] font-bold text-ink">
              Folder name (top level)
              <input
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                placeholder="Receipts"
                className={`${input} mt-1 font-normal`}
              />
            </label>
          )}
          <label className="text-[13px] font-bold text-ink">
            Only from (addresses or domains; empty: anyone)
            <input
              value={allow}
              onChange={(e) => setAllow(e.target.value)}
              placeholder="screwfix.com, bills@uber.com"
              className={`${input} mt-1 font-normal`}
            />
          </label>
          <label className="text-[13px] font-bold text-ink">
            Never from
            <input
              value={deny}
              onChange={(e) => setDeny(e.target.value)}
              placeholder="newsletters.example"
              className={`${input} mt-1 font-normal`}
            />
          </label>
          <div>
            <button type="submit" disabled={busy !== null} className={smallButton}>
              {busy === `save-${box.id}` ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </details>
    </li>
  );
}
