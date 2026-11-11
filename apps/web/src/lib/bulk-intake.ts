import { unzipSync } from "fflate";

/**
 * Bulk intake for Review (components/review/UploadToInbox.tsx): zips and whole folders are opened in the browser,
 * anything that is not a photo, PDF or bank CSV is left out (and counted, with the reason), and what remains is
 * flattened into 00 Inbox with names that never overwrite each other. Pure functions: no network, no React.
 */

export const MAX_ENTRIES = 500; // files a single drop may add (zip-bomb guard: counted before anything is unpacked)
export const MAX_TOTAL_BYTES = 500 * 1024 * 1024; // what a single drop may expand to
export const MAX_FILE_BYTES = 4 * 1024 * 1024; // OneDrive's simple upload limit (lib/graph.ts putSmallFile)
export const SCAN_BATCH = 50; // the runtime reads at most this many files per job (services/runtime/app/scan_jobs.py MAX_FILES)

export type SkipReason = "unsupported type" | "too large" | "empty";

export interface Skipped {
  name: string;
  reason: SkipReason;
}

/** One file found in a drop, a folder or a zip. `path` is where it sat (folders and zips are flattened later). */
export interface Candidate {
  path: string;
  size: number;
  blob: Blob;
}

export interface Upload {
  name: string;
  blob: Blob;
  type: string;
}

/** The user's drop is over a limit; the message says which and what to do. */
export class BulkLimitError extends Error {}

const IMAGE_EXT = ["png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff"];
const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  heic: "image/heic",
  heif: "image/heif",
  bmp: "image/bmp",
  tif: "image/tiff",
  tiff: "image/tiff",
  pdf: "application/pdf",
  csv: "text/csv",
};

export const extOf = (name: string): string => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
};

export const baseName = (path: string): string => path.split(/[\\/]/).filter(Boolean).pop() ?? "";

export const isZip = (name: string): boolean => extOf(name) === "zip";

/** Photos, PDFs and CSVs only (by extension: a zip entry has no type, and some browsers leave one off for a CSV). */
export const isSupported = (name: string): boolean => {
  const e = extOf(name);
  return e === "pdf" || e === "csv" || IMAGE_EXT.includes(e);
};

export const mimeFor = (name: string, fallback = "application/octet-stream"): string => MIME[extOf(name)] ?? fallback;

/** Archive clutter that is never a document: __MACOSX, anything starting with a dot (.DS_Store, ._receipt.jpg), Windows' own files. */
export function isJunkPath(path: string): boolean {
  const parts = path.split(/[\\/]/).filter(Boolean);
  if (parts.length === 0) return true;
  if (parts.some((p) => p === "__MACOSX" || p.startsWith("."))) return true;
  const last = parts[parts.length - 1].toLowerCase();
  return last === "thumbs.db" || last === "desktop.ini";
}

/** A file name OneDrive and Google Drive both accept: no path characters, no leading/trailing dots or spaces, not endless. */
export function safeName(name: string): string {
  let n = name.replace(/[\u0000-\u001f"*:<>?/\\|]/g, "_").trim().replace(/^\.+/, "").replace(/[. ]+$/, "");
  if (!n) n = "document";
  if (n.length > 120) {
    const e = extOf(n);
    n = n.slice(0, 120 - (e ? e.length + 1 : 0)) + (e ? `.${e}` : "");
  }
  return n;
}

/**
 * The name to upload as: the original when free, else a short suffix before the extension ("receipt-2.pdf").
 * `taken` holds lower-case names already in 00 Inbox or used earlier in this drop; the chosen name is added to it.
 */
export function uniqueName(name: string, taken: Set<string>): string {
  const clean = safeName(name);
  const dot = clean.lastIndexOf(".");
  const stem = dot > 0 ? clean.slice(0, dot) : clean;
  const ext = dot > 0 ? clean.slice(dot) : "";
  let candidate = clean;
  for (let n = 2; taken.has(candidate.toLowerCase()); n++) candidate = `${stem}-${n}${ext}`;
  taken.add(candidate.toLowerCase());
  return candidate;
}

/**
 * Opens a zip in memory. Only photos, PDFs and CSVs are unpacked; folders, junk and everything else are never
 * decompressed. The limits are checked against the sizes the archive declares, before any entry is inflated.
 * `used` is what the rest of the drop already counts towards the limits.
 */
export function unzipCandidates(
  zipName: string,
  data: Uint8Array,
  used: { entries: number; bytes: number } = { entries: 0, bytes: 0 },
): { files: Candidate[]; skipped: Skipped[] } {
  const skipped: Skipped[] = [];
  let entries = used.entries;
  let bytes = used.bytes;
  const wanted: string[] = [];
  let unpacked: Record<string, Uint8Array>;
  try {
    unpacked = unzipSync(data, {
      filter: (f) => {
        if (f.name.endsWith("/") || isJunkPath(f.name)) return false;
        if (!isSupported(f.name)) {
          skipped.push({ name: baseName(f.name), reason: "unsupported type" });
          return false;
        }
        if (f.originalSize === 0) {
          skipped.push({ name: baseName(f.name), reason: "empty" });
          return false;
        }
        if (f.originalSize > MAX_FILE_BYTES) {
          skipped.push({ name: baseName(f.name), reason: "too large" });
          return false;
        }
        entries++;
        bytes += f.originalSize;
        if (entries > MAX_ENTRIES || bytes > MAX_TOTAL_BYTES) {
          throw new BulkLimitError(
            `${zipName} holds more than ${MAX_ENTRIES} documents or expands past ${MAX_TOTAL_BYTES / (1024 * 1024)} MB, so it was not opened. Split it into smaller zips and add them one at a time.`,
          );
        }
        wanted.push(f.name);
        return true;
      },
    });
  } catch (e) {
    if (e instanceof BulkLimitError) throw e;
    throw new BulkLimitError(`${zipName} could not be opened (${(e as Error).message || "damaged or password-protected"}).`);
  }
  const files = wanted.map((name) => {
    const bytesOf = unpacked[name];
    return { path: name, size: bytesOf.length, blob: new Blob([bytesOf as BlobPart], { type: mimeFor(name) }) };
  });
  return { files, skipped };
}

/** Everything the user gave: plain files, folder contents and zips, with each zip replaced by what is inside it. */
export async function expandAll(items: Candidate[]): Promise<{ files: Candidate[]; skipped: Skipped[] }> {
  const files: Candidate[] = [];
  const skipped: Skipped[] = [];
  const used = { entries: 0, bytes: 0 };
  for (const it of items) {
    if (isJunkPath(it.path)) continue;
    if (isZip(it.path)) {
      if (it.size > MAX_TOTAL_BYTES) throw new BulkLimitError(`${baseName(it.path)} is over ${MAX_TOTAL_BYTES / (1024 * 1024)} MB, so it was not opened.`);
      const out = unzipCandidates(baseName(it.path), new Uint8Array(await it.blob.arrayBuffer()), used);
      for (const f of out.files) {
        used.entries++;
        used.bytes += f.size;
      }
      files.push(...out.files);
      skipped.push(...out.skipped);
    } else {
      files.push(it);
    }
  }
  return { files, skipped };
}

/** Filters (type, size, empty) and names what is left. `taken` = lower-case names already in 00 Inbox. */
export function planUploads(files: Candidate[], taken: Iterable<string> = []): { uploads: Upload[]; skipped: Skipped[] } {
  const used = new Set<string>(Array.from(taken, (n) => n.toLowerCase()));
  const uploads: Upload[] = [];
  const skipped: Skipped[] = [];
  for (const f of files) {
    if (isJunkPath(f.path)) continue;
    const name = baseName(f.path);
    if (!isSupported(name)) skipped.push({ name, reason: "unsupported type" });
    else if (f.size === 0) skipped.push({ name, reason: "empty" });
    else if (f.size > MAX_FILE_BYTES) skipped.push({ name, reason: "too large" });
    else uploads.push({ name: uniqueName(name, used), blob: f.blob, type: f.blob.type || mimeFor(name) });
  }
  if (uploads.length > MAX_ENTRIES) {
    throw new BulkLimitError(`That is ${uploads.length} documents; the limit for one drop is ${MAX_ENTRIES}. Add them in smaller groups.`);
  }
  return { uploads, skipped };
}

/** "2 unsupported type, 1 too large" */
export function skipSummary(skipped: Skipped[]): string {
  const counts = new Map<SkipReason, number>();
  for (const s of skipped) counts.set(s.reason, (counts.get(s.reason) ?? 0) + 1);
  return Array.from(counts, ([r, n]) => `${n} ${r}`).join(", ");
}

/** Runs `worker` over `items` with at most `limit` at once; results keep the order of `items`. Never rejects: the worker reports its own failures. */
export async function mapLimit<T, R>(items: T[], limit: number, worker: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  const lane = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await worker(items[i], i);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane));
  return out;
}

export function chunk<T>(list: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

// ---- Reading what the browser hands over (not unit-tested: needs a real drop) ----

interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  fullPath: string;
  file?: (ok: (f: File) => void, err: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (e: FsEntry[]) => void, err: (e: unknown) => void) => void };
}

async function walk(entry: FsEntry, out: Candidate[], depth = 0): Promise<void> {
  if (entry.name.startsWith(".") || entry.name === "__MACOSX" || depth > 20) return;
  if (entry.isFile && entry.file) {
    const f = await new Promise<File>((ok, err) => entry.file!(ok, err));
    out.push({ path: entry.fullPath.replace(/^\//, "") || f.name, size: f.size, blob: f });
  } else if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    for (;;) {
      // readEntries hands back at most ~100 at a time: keep asking until it is empty.
      const batch = await new Promise<FsEntry[]>((ok, err) => reader.readEntries(ok, err));
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, out, depth + 1);
    }
  }
}

/** Files and folders from a drop. The entries are taken first: the DataTransfer is empty once anything is awaited. */
export async function candidatesFromDrop(dt: DataTransfer): Promise<Candidate[]> {
  const entries: FsEntry[] = [];
  const plain: File[] = [];
  for (const item of Array.from(dt.items ?? [])) {
    if (item.kind !== "file") continue;
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FsEntry | null }).webkitGetAsEntry?.();
    if (entry) entries.push(entry);
    else {
      const f = item.getAsFile();
      if (f) plain.push(f);
    }
  }
  if (entries.length === 0 && plain.length === 0) plain.push(...Array.from(dt.files));
  const out: Candidate[] = plain.map((f) => ({ path: f.name, size: f.size, blob: f }));
  for (const e of entries) await walk(e, out);
  return out;
}

/** Files from the pickers: a folder pick carries each file's path in webkitRelativePath. */
export function candidatesFromFiles(files: FileList | File[]): Candidate[] {
  return Array.from(files).map((f) => ({
    path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name,
    size: f.size,
    blob: f,
  }));
}
