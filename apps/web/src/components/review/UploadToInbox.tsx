"use client";

import { useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { FOLDER } from "@/lib/folders";
import { putSmallFile } from "@/lib/graph";

interface FileResult {
  name: string;
  ok: boolean;
  error?: string;
}

/** F3 intake (web): put photos/PDFs into the user's own "00 Inbox" folder. Nothing goes to our servers. */
export default function UploadToInbox({ account, onDone }: { account: AccountInfo; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [results, setResults] = useState<FileResult[]>([]);
  const [dragging, setDragging] = useState(false);

  async function onFiles(files: FileList | File[] | null) {
    if (!files || files.length === 0 || busy) return;
    const list = Array.from(files);
    setBusy(true);
    setProgress(null);
    setResults([]);
    const done: FileResult[] = [];
    try {
      for (let i = 0; i < list.length; i++) {
        const f = list[i];
        setProgress(`Uploading ${i + 1} of ${list.length}: ${f.name}`);
        try {
          if (f.size > 4 * 1024 * 1024) throw new Error(`${f.name} is over 4 MB — please use a smaller photo for now.`);
          await putSmallFile(account, `${FOLDER.inbox}/${f.name}`, f, f.type || "application/octet-stream");
          done.push({ name: f.name, ok: true });
        } catch (e) {
          done.push({ name: f.name, ok: false, error: (e as Error).message });
        }
        setResults([...done]);
      }
      const okCount = done.filter((r) => r.ok).length;
      if (okCount > 0) onDone();
      setProgress(null);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const okCount = results.filter((r) => r.ok).length;
  const errors = results.filter((r) => !r.ok);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void onFiles(e.dataTransfer.files);
      }}
      className={`flex flex-wrap items-center gap-3 rounded-2xl border-2 border-dashed p-3 ${
        dragging ? "border-teal bg-teal-tint" : "border-border"
      }`}
    >
      <input
        ref={input}
        type="file"
        accept="image/*,.pdf"
        multiple
        aria-label="Choose receipt photos or PDFs"
        className="hidden"
        onChange={(e) => void onFiles(e.target.files)}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
      >
        {busy ? "Uploading…" : "Add a receipt"}
      </button>
      <span className="text-sm text-muted">or drop photos or PDFs here — they go to 00 Inbox</span>
      <div className="w-full" aria-live="polite">
        {progress && (
          <p role="status" className="text-sm font-semibold text-teal-dark">
            {progress}
          </p>
        )}
        {results.length > 0 && (
          <div role="status" className="flex flex-col gap-1">
            {okCount > 0 && (
              <p className="text-sm text-muted">
                {okCount} file{okCount === 1 ? "" : "s"} added to 00 Inbox. Press “Scan 00 Inbox now”.
              </p>
            )}
            {errors.length > 0 && (
              <ul className="flex flex-col gap-1">
                {errors.map((r) => (
                  <li key={r.name} className="text-sm font-semibold text-warn-ink">
                    {r.name}: {r.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
