"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, isPersonalAccount, msalConfigured, SIGN_IN_SCOPES } from "@/lib/msal";
import { setupBooksFolder, type DriveItem, type SetupProgress } from "@/lib/graph";
import { useNextParam, withNext } from "@/components/connect/ConnectSteps";

type Phase = "loading" | "signed-out" | "signed-in" | "creating" | "ready" | "error";

/** Never a raw error on screen: one sentence the user can act on. */
function friendlySignInError(e: unknown): string {
  const msg = e instanceof Error ? e.message : "";
  if (/cancel|cancelled|user_cancelled|access_denied|AADB2C90091/i.test(msg)) {
    return "Sign-in was cancelled before it finished — try again when you're ready.";
  }
  return "Sign-in did not finish — try again.";
}

/** Never a raw error on screen: one sentence the user can act on. */
function friendlyFolderError(e: unknown): string {
  const msg = e instanceof Error ? e.message : "";
  if (/PendingProvisioning|pending provisioning/i.test(msg)) {
    return "Your OneDrive is still being set up by Microsoft — open onedrive.live.com once, then try again in a few minutes.";
  }
  return "OneDrive would not let us create the folder — check you're online and try again.";
}

export default function ConnectMicrosoft() {
  const next = useNextParam();
  const [phase, setPhase] = useState<Phase>("loading");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [root, setRoot] = useState<DriveItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"signin" | "folder" | "setup" | null>(null);

  useEffect(() => {
    (async () => {
      if (!msalConfigured()) {
        setError("Microsoft sign-in is not configured on this site yet — try again later.");
        setErrorKind("setup");
        setPhase("error");
        return;
      }
      const msal = await getMsal();
      const result = await msal.handleRedirectPromise().catch((e: unknown) => {
        setError(friendlySignInError(e));
        setErrorKind("signin");
        return null;
      });
      const acct = result?.account ?? msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
      if (acct) msal.setActiveAccount(acct);
      setAccount(acct);
      setPhase(acct ? "signed-in" : "signed-out");
    })();
  }, []);

  async function signIn() {
    setError(null);
    setErrorKind(null);
    const msal = await getMsal();
    try {
      await msal.loginRedirect({ scopes: SIGN_IN_SCOPES, prompt: "select_account" });
    } catch (e) {
      setError(friendlySignInError(e));
      setErrorKind("signin");
      setPhase("signed-out");
    }
  }

  async function signOut() {
    const msal = await getMsal();
    await msal.logoutRedirect();
  }

  async function createFolder() {
    if (!account) return;
    setPhase("creating");
    setError(null);
    setErrorKind(null);
    try {
      const item = await setupBooksFolder(account, setProgress);
      setRoot(item);
      setPhase("ready");
    } catch (e) {
      setError(friendlyFolderError(e));
      setErrorKind("folder");
      setPhase("error");
    }
  }

  const btn = "h-12 rounded-xl px-5 text-[15px] font-bold";
  const primary = `${btn} w-full bg-[#0F6E63] text-white`;

  return (
    <div className="mt-6 space-y-4">
      {phase === "loading" && <p className="text-sm text-[#4B5159]">Checking your sign-in…</p>}

      {(phase === "signed-out" || (phase === "error" && !account)) && (
        <div className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
          <h2 className="text-[15px] font-extrabold text-[#1B1F24]">What signing in asks for, and why</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-[#4B5159]">
            <li>Who you are, so the app can open your OneDrive.</li>
            <li>Permission to read and write its own books folder only — never the rest of your OneDrive.</li>
            <li>To stay signed in on this device, so you don&apos;t sign in on every visit.</li>
          </ul>
        </div>
      )}

      {phase === "signed-out" && (
        <button onClick={signIn} className={primary}>
          Sign in with Microsoft
        </button>
      )}

      {account && phase !== "signed-out" && (
        <div className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
          <div className="text-sm text-[#4B5159]">Signed in as</div>
          <div className="font-bold text-[#1B1F24]">{account.username}</div>
          <div className="mt-1 text-xs text-[#4B5159]">
            {isPersonalAccount(account)
              ? "Personal account · folder will be OneDrive › Apps › Accnomos"
              : "Work or school account · folder will be OneDrive › Accnomos"}
          </div>
          <button onClick={signOut} className="mt-2 text-xs font-bold text-[#0A4F47]">
            Use a different account
          </button>
        </div>
      )}

      {(phase === "signed-in" || (phase === "error" && account)) && (
        <button onClick={createFolder} className={primary}>
          Create my Accnomos folder
        </button>
      )}

      {phase === "creating" && progress && (
        <div className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
          <div className="text-sm font-bold text-[#1B1F24]">{progress.step}</div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded bg-[#F4F3EE]">
            <div
              className="h-2 bg-[#0F6E63] transition-all"
              style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {phase === "ready" && root && (
        <div className="rounded-2xl border border-[#0F6E63] bg-[#E6F1EF] p-4">
          <div className="font-extrabold text-[#0A4F47]">Your folder is ready.</div>
          <p className="mt-1 text-sm text-[#1B1F24]">
            These are your books. You can open them without the app, and they stay yours if you disconnect.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            <Link
              href={withNext("/connect/ai", next)}
              className={`${btn} inline-flex items-center justify-center bg-[#0F6E63] text-white`}
            >
              Continue
            </Link>
            {root.webUrl && (
              <a
                href={root.webUrl}
                target="_blank"
                rel="noreferrer"
                className={`${btn} inline-flex items-center justify-center border border-[#0F6E63] bg-white text-[#0A4F47]`}
              >
                Open in OneDrive
              </a>
            )}
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-2xl border border-[#F3C892] bg-[#FFF7ED] p-4 text-sm text-[#8A3F06]">
          <p>{error}</p>
          {errorKind === "signin" && (
            <button onClick={signIn} className={`${btn} mt-3 w-full bg-[#0F6E63] text-white`}>
              Try signing in again
            </button>
          )}
          {errorKind === "folder" && account && (
            <button onClick={createFolder} className={`${btn} mt-3 w-full bg-[#0F6E63] text-white`}>
              Try creating the folder again
            </button>
          )}
        </div>
      )}
    </div>
  );
}
