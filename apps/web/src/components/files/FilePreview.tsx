"use client";

import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getFileBlob, type DriveItem } from "@/lib/graph";
import { modified, OpenLink, size } from "@/components/files/FilesTree";

const TEXT_LIMIT = 100_000; // first 100 KB of a JSON/CSV, with a note

function kindOf(item: DriveItem): "image" | "pdf" | "text" | "other" {
  const mime = item.file?.mimeType ?? "";
  const name = item.name.toLowerCase();
  if (mime.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp)$/.test(name)) return "image";
  if (mime === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (
    mime.startsWith("text/") ||
    mime === "application/json" ||
    /\.(json|csv|txt|jsonl|md)$/.test(name)
  )
    return "text";
  return "other";
}

/** A file preview read live from the user's OneDrive through the existing Graph helpers. */
export default function FilePreview({
  account,
  path,
  item,
  onClose,
}: {
  account: AccountInfo;
  path: string;
  item: DriveItem;
  onClose: () => void;
}) {
  const kind = kindOf(item);
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let objectUrl = "";
    let live = true;
    getFileBlob(account, path)
      .then(async (blob) => {
        if (kind === "text") {
          const full = await blob.text();
          if (!live) return;
          setTruncated(full.length > TEXT_LIMIT);
          setText(full.slice(0, TEXT_LIMIT));
        } else if (kind === "image" || kind === "pdf") {
          objectUrl = URL.createObjectURL(blob);
          if (live) setUrl(objectUrl);
          else URL.revokeObjectURL(objectUrl);
        }
      })
      .catch((e) => {
        if (live) setFailed((e as Error).message);
      });
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, path]);

  async function copy() {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section
      aria-label={`Preview: ${item.name}`}
      className="flex min-h-0 min-w-0 flex-col gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5"
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-extrabold">{item.name}</h2>
          <p className="text-[13px] font-medium tabular-nums text-muted">
            {size(item.size)} · {modified(item.lastModifiedDateTime)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 whitespace-nowrap rounded-xl border border-border px-3 py-1.5 text-[13px] font-bold"
        >
          Close preview
        </button>
      </div>

      {failed ? (
        <p role="alert" className="text-sm font-semibold text-warn-ink">
          Could not load a preview: {failed}
        </p>
      ) : kind === "image" ? (
        url ? (
          // eslint-disable-next-line @next/next/no-img-element -- a blob: URL from the user's OneDrive, not a static asset
          <img src={url} alt={item.name} decoding="async" className="max-h-[60dvh] w-full rounded-xl border border-border object-contain" />
        ) : (
          <p role="status" className="text-sm text-muted">
            Loading the image…
          </p>
        )
      ) : kind === "pdf" ? (
        url ? (
          <iframe src={url} title={`PDF: ${item.name}`} className="h-[60dvh] w-full rounded-xl border border-border" />
        ) : (
          <p role="status" className="text-sm text-muted">
            Loading the PDF…
          </p>
        )
      ) : kind === "text" ? (
        text === null ? (
          <p role="status" className="text-sm text-muted">
            Loading the file…
          </p>
        ) : (
          <div className="flex min-h-0 min-w-0 flex-col gap-2">
            <div>
              <button
                type="button"
                onClick={copy}
                className="shrink-0 whitespace-nowrap rounded-xl border border-border bg-white px-3 py-1.5 text-[13px] font-bold"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="max-h-[50dvh] min-w-0 overflow-auto rounded-xl bg-ground p-3 text-[12px] leading-5">
              {text}
            </pre>
            {truncated && <p className="text-[13px] text-muted">Showing the first 100 KB of the file.</p>}
          </div>
        )
      ) : (
        <p className="text-sm text-muted">No preview for this kind of file — open it in OneDrive instead.</p>
      )}

      <div className="flex flex-wrap gap-2">
        <OpenLink item={item} />
      </div>
    </section>
  );
}
