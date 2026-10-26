"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getMsal, isPersonalAccount, msalConfigured, SIGN_IN_SCOPES, storageScopesFor } from "@/lib/msal";
import { setupBooksFolder, type DriveItem, type SetupProgress } from "@/lib/graph";

type Phase = "loading" | "signed-out" | "signed-in" | "creating" | "ready" | "error";

export default function ConnectMicrosoft() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [root, setRoot] = useState<DriveItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      if (!msalConfigured()) {
        setError("Microsoft sign-in is not configured (NEXT_PUBLIC_MS_CLIENT_ID missing).");
        setPhase("error");
        return;
      }
      const msal = await getMsal();
      const result = await msal.handleRedirectPromise().catch((e: Error) => {
        setError(e.message);
        return null;
      });
      const acct = result?.account ?? msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
      if (acct) msal.setActiveAccount(acct);
      setAccount(acct);
      setPhase(acct ? "signed-in" : "signed-out");
    })();
  }, []);

  async function signIn() {
    const msal = await getMsal();
    await msal.loginRedirect({ scopes: SIGN_IN_SCOPES, prompt: "select_account" });
  }

  async function signOut() {
    const msal = await getMsal();
    await msal.logoutRedirect();
  }

  async function createFolder() {
    if (!account) return;
    setPhase("creating");
    setError(null);
    try {
      const item = await setupBooksFolder(account, setProgress);
      setRoot(item);
      setPhase("ready");
    } catch (e) {
      setError((e as Error).message);
      setPhase("error");
    }
  }

  const btn = "h-12 rounded-xl px-5 text-[15px] font-bold";

  return (
    <div className="mt-6 space-y-4">
      {phase === "loading" && <p className="text-sm text-[#4B5159]">Checking your sign-in…</p>}

      {phase === "signed-out" && (
        <button onClick={signIn} className={`${btn} w-full bg-[#0F6E63] text-white`}>
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
            {" · "}permission: {storageScopesFor(account).join(", ")}
          </div>
          <button onClick={signOut} className="mt-2 text-xs font-bold text-[#0A4F47]">
            Use a different account
          </button>
        </div>
      )}

      {phase === "signed-in" && (
        <button onClick={createFolder} className={`${btn} w-full bg-[#0F6E63] text-white`}>
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
          {root.webUrl && (
            <a
              href={root.webUrl}
              target="_blank"
              rel="noreferrer"
              className={`${btn} mt-3 inline-flex items-center bg-white text-[#0A4F47] border border-[#0F6E63]`}
            >
              Open in OneDrive
            </a>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[#F3C892] bg-[#FFF7ED] p-4 text-sm text-[#8A3F06]">{error}</div>
      )}
    </div>
  );
}
