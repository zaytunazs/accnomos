import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { zipSync } from "fflate";
import { BulkLimitError, chunk, expandAll, mapLimit, planUploads, uniqueName, unzipCandidates } from "../src/lib/bulk-intake";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

// Zips and folders into 00 Inbox: the pure helper (src/lib/bulk-intake.ts) first, then the Review page end to end.

const enc = (s: string) => new TextEncoder().encode(s);
const PDF = enc("%PDF-1.4 test");

test("unzip: keeps photos, PDFs and CSVs, drops junk and the rest, and says why", () => {
  const zip = zipSync({
    "March/receipt.pdf": PDF,
    "March/photo.JPG": enc("jpg"),
    "bank.csv": enc("a,b"),
    "__MACOSX/March/._receipt.pdf": enc("x"),
    ".DS_Store": enc("x"),
    "notes.docx": enc("x"),
    "empty.pdf": new Uint8Array(0),
  });
  const { files, skipped } = unzipCandidates("books.zip", zip);
  expect(files.map((f) => f.path).sort()).toEqual(["March/photo.JPG", "March/receipt.pdf", "bank.csv"]);
  expect(files.find((f) => f.path.endsWith(".JPG"))!.blob.type).toBe("image/jpeg");
  expect(skipped.map((s) => `${s.name}:${s.reason}`).sort()).toEqual(["empty.pdf:empty", "notes.docx:unsupported type"]);
});

test("unzip: a zip over the file or size limit is refused with a clear message", () => {
  const many = Object.fromEntries(Array.from({ length: 501 }, (_, i) => [`r${i}.pdf`, PDF]));
  expect(() => unzipCandidates("big.zip", zipSync(many))).toThrow(BulkLimitError);
  expect(() => unzipCandidates("big.zip", zipSync(many))).toThrow(/more than 500 documents/);
  expect(() => unzipCandidates("bad.zip", enc("not a zip"))).toThrow(/could not be opened/);
});

test("names: the original is kept, a clash gets a short suffix, path characters go", () => {
  const taken = new Set(["receipt.pdf"]);
  expect(uniqueName("receipt.pdf", taken)).toBe("receipt-2.pdf");
  expect(uniqueName("receipt.pdf", taken)).toBe("receipt-3.pdf");
  expect(uniqueName("Receipt.PDF", taken)).toBe("Receipt-4.PDF");
  expect(uniqueName("a:b?.png", new Set())).toBe("a_b_.png");
});

test("plan: flattens folders, skips unsupported, too large and empty, renames duplicates, counts across zips", async () => {
  const f = (path: string, size: number) => ({ path, size, blob: new Blob([new Uint8Array(size)]) });
  const zip = zipSync({ "inner/receipt.pdf": PDF });
  const { files, skipped: fromZips } = await expandAll([
    f("Jan/receipt.pdf", 10),
    f("Feb/receipt.pdf", 10),
    f("Feb/.hidden.pdf", 10),
    f("Feb/readme.txt", 10),
    f("Feb/huge.png", 5 * 1024 * 1024),
    f("Feb/zero.csv", 0),
    { path: "extra.zip", size: zip.length, blob: new Blob([zip as BlobPart]) },
  ]);
  const { uploads, skipped } = planUploads(files, ["Receipt.pdf"]);
  expect(uploads.map((u) => u.name)).toEqual(["receipt-2.pdf", "receipt-3.pdf", "receipt-4.pdf"]);
  expect([...skipped, ...fromZips].map((s) => s.reason).sort()).toEqual(["empty", "too large", "unsupported type"]);
});

test("mapLimit never runs more than the limit at once; chunk splits in 50s", async () => {
  let live = 0;
  let peak = 0;
  await mapLimit(Array.from({ length: 20 }, (_, i) => i), 4, async () => {
    peak = Math.max(peak, ++live);
    await new Promise((r) => setTimeout(r, 5));
    live--;
  });
  expect(peak).toBe(4);
  expect(chunk(Array.from({ length: 120 }, (_, i) => i), 50).map((c) => c.length)).toEqual([50, 50, 20]);
});

test("Review: a zip and a folder of documents are flattened into 00 Inbox, summarised, and read in batches of 50", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/review");
  const gold = await runtime.goldPng();
  const starts: string[] = [];
  page.on("request", (r) => new URL(r.url()).pathname === "/books/scan/jobs" && r.method() === "POST" && starts.push(r.postData() ?? ""));

  const entries: Record<string, Uint8Array> = { "notes.txt": enc("x"), "__MACOSX/._a.png": enc("x") };
  for (let i = 0; i < 55; i++) entries[`2026/r${i}.png`] = new Uint8Array(gold);
  await page.locator('input[type="file"]').first().setInputFiles({
    name: "dump.zip",
    mimeType: "application/zip",
    buffer: Buffer.from(zipSync(entries)),
  });
  await expect(page.getByText("55 files added to 00 Inbox. Reading now")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("1 skipped: 1 unsupported type")).toBeVisible();
  expect(starts.map((s) => JSON.parse(s).names.length)).toEqual([50, 5]);
  expect((await runtime.files()).filter((f) => f.startsWith("00 Inbox/")).length).toBeGreaterThanOrEqual(55);

  // The folder picker flattens a nested folder and renames a clash with what is already in 00 Inbox.
  const dir = mkdtempSync(join(tmpdir(), "accnomos-folder-"));
  mkdirSync(join(dir, "docs", "march"), { recursive: true });
  writeFileSync(join(dir, "docs", "march", "r0.png"), gold);
  await page.locator('input[type="file"]').nth(1).setInputFiles(join(dir, "docs"));
  await expect(page.getByText("1 file added to 00 Inbox")).toBeVisible({ timeout: 30_000 });
  expect(await runtime.files()).toContain("00 Inbox/r0-2.png");
});
