"use client";

import { useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { FOLDER } from "@/lib/folders";
import { putSmallFile } from "@/lib/graph";

/** F3 intake (web): put a photo/PDF into the user's own "00 Inbox" folder. Nothing goes to our servers. */
export default function UploadToInbox({ account, onDone }: { account: AccountInfo; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setMsg(null);
    try {
      for (const f of Array.from(files)) {
        if (f.size > 4 * 1024 * 1024) throw new Error(`${f.name} is over 4 MB — please use a smaller photo for now.`);
        await putSmallFile(account, `${FOLDER.inbox}/${f.name}`, f, f.type || "application/octet-stream");
      }
      setMsg(`${files.length} file${files.length === 1 ? "" : "s"} added to 00 Inbox. Press “Scan 00 Inbox now”.`);
      onDone();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <input ref={input} type="file" accept="image/*,.pdf" multiple aria-label="Choose receipt photos or PDFs" className="hidden" onChange={(e) => onFiles(e.target.files)} />
      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
      >
        {busy ? "Uploading…" : "Add a receipt"}
      </button>
      {msg && <span role="status" className="text-sm text-muted">{msg}</span>}
    </div>
  );
}
