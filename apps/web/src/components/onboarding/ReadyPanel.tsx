"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import { loadBusiness } from "@/lib/business";
import { getRoot, putSmallFile } from "@/lib/graph";
import { getMsal, isPersonalAccount, msalConfigured } from "@/lib/msal";
import { useNextParam, withNext } from "@/components/connect/ConnectSteps";
import { markReceiptTried } from "@/components/home/SetupChecklist";
import SampleBooks from "@/components/home/SampleBooks";

const NEXT_STEPS = [
  "Drop receipts into 00 Inbox or snap them in the app",
  "Accnomos reads them with Meta AI and proposes entries",
  "You approve; code posts and keeps the VAT return",
];

/** Connect step 4: the folder is in place — prove it with the sample receipt. */
export default function ReadyPanel() {
  const router = useRouter();
  const next = useNextParam();
  const [businessName, setBusinessName] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountInfo | null | undefined>(undefined);
  const [folderMissing, setFolderMissing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    const saved = loadBusiness();
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => setBusinessName(saved?.name.trim() ? saved.name.trim() : null));
    (async () => {
      try {
        if (!msalConfigured()) return setAccount(null);
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        setAccount(acct);
        if (acct) {
          try {
            await getRoot(acct);
          } catch {
            setFolderMissing(true);
          }
        }
      } catch {
        setAccount(null);
      }
    })();
  }, []);

  /** Put public/sample-receipt.png into 00 Inbox, then open Review: the first receipt, working. */
  async function trySampleReceipt() {
    if (!account || uploading) return;
    setUploading(true);
    setUploadError(null);
    try {
      const res = await fetch("/sample-receipt.png");
      if (!res.ok) throw new Error(`sample receipt -> ${res.status}`);
      const blob = await res.blob();
      await putSmallFile(account, "00 Inbox/sample-receipt.png", blob, blob.type || "image/png");
      markReceiptTried();
      router.push("/review");
    } catch {
      setUploadError("The sample receipt did not upload — check you're online and try again.");
    } finally {
      setUploading(false);
    }
  }

  const btn = "inline-flex h-12 items-center justify-center rounded-xl px-5 text-[15px] font-bold";

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-2xl border border-teal bg-teal-tint p-4">
        <div className="font-extrabold text-teal-dark">Your folder is ready</div>
        <p className="mt-1 text-sm text-ink">
          {account && !isPersonalAccount(account)
            ? "OneDrive › Accnomos"
            : "OneDrive › Apps › Accnomos"}
        </p>
      </div>

      <p className="text-[15px] font-bold text-ink">
        {businessName ? `${businessName} is set up.` : "You're set up."}
      </p>

      {account === null && (
        <div role="alert" className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
          <p>You&apos;re signed out — sign in first so the sample receipt has a folder to land in.</p>
          <Link href={withNext("/connect", next)} className={`${btn} mt-3 w-full bg-teal text-white`}>
            Back to step 1
          </Link>
        </div>
      )}

      {folderMissing && account && (
        <div role="alert" className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
          <p>We couldn&apos;t find your books folder yet — create it in step 1 first.</p>
          <Link href={withNext("/connect", next)} className={`${btn} mt-3 w-full bg-teal text-white`}>
            Back to step 1
          </Link>
        </div>
      )}

      <ol className="space-y-2">
        {NEXT_STEPS.map((step, i) => (
          <li
            key={step}
            className="flex items-start gap-3 rounded-2xl border border-border bg-white p-4 text-[15px] text-ink"
          >
            <span
              aria-hidden="true"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-tint text-[13px] font-extrabold text-teal-dark"
            >
              {i + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>

      <button
        type="button"
        onClick={trySampleReceipt}
        disabled={!account || uploading}
        className={`${btn} w-full bg-teal font-extrabold text-white hover:bg-teal-dark disabled:opacity-60`}
      >
        {uploading ? "Adding the sample receipt…" : "Try the sample receipt"}
      </button>
      <p className="text-xs text-muted">Puts the sample receipt in 00 Inbox and opens Review.</p>

      {uploadError && (
        <div role="alert" className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-sm text-warn-ink">
          <p>{uploadError}</p>
          <button
            type="button"
            onClick={trySampleReceipt}
            disabled={uploading}
            className={`${btn} mt-3 w-full bg-teal text-white disabled:opacity-60`}
          >
            Try again
          </button>
        </div>
      )}

      {/* An empty folder: or start from the sample books (they never go into a folder that has books). */}
      {account && !folderMissing && <SampleBooks account={account} place="connect" />}

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-3">
        <Link
          href="/files"
          className={`${btn} border border-teal bg-white text-teal-dark`}
        >
          See your files
        </Link>
        <Link
          href={next ?? "/"}
          className={`${btn} flex-1 bg-teal font-extrabold text-white hover:bg-teal-dark`}
        >
          {next ? "Continue" : "Go to Home"}
        </Link>
      </div>
    </div>
  );
}
