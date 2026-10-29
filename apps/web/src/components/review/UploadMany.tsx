"use client";

import { useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { FOLDER } from "@/lib/folders";
import { getFileWebUrl, putSmallFile } from "@/lib/graph";

interface FileResult {
  name: string;
  ok: boolean;
  error?: string;
}

/** A dropped folder's files, flattened (webkitGetAsEntry; falls back to plain files). */
async function droppedFiles(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items ?? [])
    .map((i) => (typeof i.webkitGetAsEntry === "function" ? i.webkitGetAsEntry() : null))
    .filter((e): e is FileSystemEntry => e !== null);
  if (entries.length === 0) return Array.from(dt.files ?? []);
  const out: File[] = [];
  async function walk(entry: FileSystemEntry): Promise<void> {
    if (entry.isFile) {
      const file = await new Promise<File | null>((resolve) => (entry as FileSystemFileEntry).file(resolve, () => resolve(null)));
      if (file) out.push(file);
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch: FileSystemEntry[] = await new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
        if (batch.length === 0) break;
        for (const child of batch) await walk(child);
      }
    }
  }
  for (const entry of entries) await walk(entry);
  return out.length > 0 ? out : Array.from(dt.files ?? []);
}

/**
 * "Upload many": multi-select, a dropped folder, or a .zip, written straight into
 * the user's own "01 Bulk upload" folder (and only there). Nothing goes to our servers.
 */
export default function UploadMany({ account, onDone }: { account: AccountInfo; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [results, setResults] = useState<FileResult[]>([]);
  const [dragging, setDragging] = useState(false);
  const [folderUrl, setFolderUrl] = useState<string | null>(null);

  async function onFiles(files: FileList | File[] | null, fromDrop = false) {
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
          if (f.size > 4 * 1024 * 1024) throw new Error(`${f.name} is over 4 MB — please use a smaller file for now.`);
          await putSmallFile(account, `${FOLDER.bulk}/${f.name}`, f, f.type || "application/octet-stream");
          done.push({ name: f.name, ok: true });
        } catch (e) {
          done.push({ name: f.name, ok: false, error: (e as Error).message });
        }
        setResults([...done]);
      }
      if (done.some((r) => r.ok)) onDone();
      setProgress(null);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
    void fromDrop;
  }

  async function openFolder(e: React.MouseEvent) {
    e.preventDefault();
    if (folderUrl) {
      window.open(folderUrl, "_blank", "noopener");
      return;
    }
    try {
      const url = await getFileWebUrl(account, FOLDER.bulk);
      if (url) {
        setFolderUrl(url);
        window.open(url, "_blank", "noopener");
      }
    } catch {
      /* no shareable link yet: the folder is created on the first upload */
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
        void droppedFiles(e.dataTransfer).then((files) => onFiles(files, true));
      }}
      className={`flex flex-wrap items-center gap-3 rounded-2xl border-2 border-dashed p-3 ${
        dragging ? "border-teal bg-teal-tint" : "border-border"
      }`}
    >
      <input
        ref={input}
        type="file"
        accept="image/*,.pdf,.zip,.csv,.eml,.txt"
        multiple
        aria-label="Choose files or a zip for the bulk folder"
        className="hidden"
        onChange={(e) => void onFiles(e.target.files)}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="h-11 whitespace-nowrap rounded-xl border border-border bg-white px-5 text-[15px] font-bold disabled:opacity-60"
      >
        {busy ? "Uploading…" : "Upload many"}
      </button>
      <span className="text-sm text-muted">
        or drop files, a folder or a .zip here — they go to {FOLDER.bulk} only.{" "}
        <button type="button" onClick={openFolder} className="font-bold text-teal underline underline-offset-2">
          Open the folder in OneDrive
        </button>
      </span>
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
                {okCount} file{okCount === 1 ? "" : "s"} added to {FOLDER.bulk}. Press “Process the bulk folder”.
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
