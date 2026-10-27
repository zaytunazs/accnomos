"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { getToken, isPersonalAccount, storageScopesFor } from "./msal";

/** Test-mode builds talk to the runtime's Graph look-alike over its fake storage (services/runtime/app/testmode.py). */
const GRAPH =
  process.env.NEXT_PUBLIC_TEST_MODE === "1" ? `${RUNTIME_URL}/__test/graph/v1.0` : "https://graph.microsoft.com/v1.0";

/** PRD §4.1 folder tree. Personal accounts: OneDrive app folder (Apps/Accnomos). Work accounts: /Accnomos in the root. */
export const FOLDERS = [
  "00 Inbox",
  "01 Receipts",
  "02 Sales invoices",
  "03 Bank statements",
  "04 Needs a look",
  "05 VAT returns",
  "06 Reports",
  "_System",
  "_System/audit",
  "_System/docs",
  "_System/proposals",
  "_System/Ledger/events",
];

export const README_TEXT = `These are your books.

This folder was created by Accnomos. Everything the app knows about your business is in here, in plain files:
- 00 Inbox: drop receipts, invoices or statements here (photo, PDF, email attachment) and Accnomos will read them.
- 01-02: documents Accnomos has filed, renamed like "2026-10-21 Screwfix £38.47.pdf".
- 03 Bank statements: the statement files you imported.
- 04 Needs a look: anything odd (duplicates, missing VAT number, unreadable), with a reason.
- 05 VAT returns: the 9-box calculation and HMRC receipt for each period.
- Books.xlsx: a spreadsheet of your books, rebuilt from the files in _System. Do not edit it; it is overwritten.
- _System: the ledger events and the audit log (never edited: a correction is a new entry that reverses
  the old one), plus rules you approved, contacts, jobs, staff, timesheets, vehicles and your mileage log.

You can open all of this without the app. If you disconnect Accnomos, the files stay yours.
Sample data is labelled "SAMPLE — FICTIONAL COMPANY".
`;

export interface DriveItem {
  id: string;
  name: string;
  webUrl?: string;
  eTag?: string;
  size?: number; // bytes; for a folder, everything inside it
  lastModifiedDateTime?: string;
  folder?: { childCount: number };
  file?: { mimeType: string };
}

async function graph<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${GRAPH}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Graph ${init.method ?? "GET"} ${path} -> ${res.status}: ${body.slice(0, 300)}`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/**
 * Graph address of an item inside the books folder, per account type (path-based addressing).
 * MSA:  /me/drive/special/approot            and /me/drive/special/approot:/00 Inbox
 * Work: /me/drive/root:/Accnomos             and /me/drive/root:/Accnomos/00 Inbox
 * Append ":/children" or ":/content" to a path-addressed item; the bare approot takes "/children".
 */
export function itemPath(account: AccountInfo, relPath = ""): string {
  const enc = relPath.split("/").map(encodeURIComponent).join("/");
  if (isPersonalAccount(account)) {
    return relPath ? `/me/drive/special/approot:/${enc}` : "/me/drive/special/approot";
  }
  return relPath ? `/me/drive/root:/Accnomos/${enc}` : "/me/drive/root:/Accnomos";
}

/** The books root itself (for its webUrl and total size). Read-only: never creates the folder. */
export async function getRoot(account: AccountInfo): Promise<DriveItem> {
  const token = await getToken(storageScopesFor(account));
  return graph<DriveItem>(token, `${itemPath(account)}?$select=id,name,webUrl,size,lastModifiedDateTime,folder`);
}

/** OneDrive web URL of one file or folder in the books tree, for opening a cited file. Null when it cannot be read. */
export async function getFileWebUrl(account: AccountInfo, relPath: string): Promise<string | null> {
  try {
    const token = await getToken(storageScopesFor(account));
    const item = await graph<DriveItem>(token, `${itemPath(account, relPath)}?$select=webUrl`);
    return item.webUrl ?? null;
  } catch {
    return null;
  }
}

/** Direct children of a folder in the books tree ("" = the root), following Graph's paging. Read-only. */
export async function listChildren(account: AccountInfo, relPath = ""): Promise<DriveItem[]> {
  const token = await getToken(storageScopesFor(account));
  const select = "$select=id,name,webUrl,size,lastModifiedDateTime,folder,file&$top=200";
  let path: string | null = `${itemPath(account, relPath)}${relPath ? ":" : ""}/children?${select}`;
  const items: DriveItem[] = [];
  while (path) {
    const page: { value: DriveItem[]; "@odata.nextLink"?: string } = await graph(token, path);
    items.push(...page.value);
    const next = page["@odata.nextLink"];
    path = next ? next.replace(GRAPH, "") : null;
  }
  return items;
}

export async function ensureRoot(account: AccountInfo): Promise<DriveItem> {
  const token = await getToken(storageScopesFor(account));
  if (isPersonalAccount(account)) {
    return graph<DriveItem>(token, "/me/drive/special/approot"); // created on first call, named after the app
  }
  try {
    return await graph<DriveItem>(token, "/me/drive/root:/Accnomos");
  } catch {
    return graph<DriveItem>(token, "/me/drive/root/children", {
      method: "POST",
      body: JSON.stringify({ name: "Accnomos", folder: {}, "@microsoft.graph.conflictBehavior": "fail" }),
    });
  }
}

/**
 * Get-or-create a folder. Lookup is path-based; creation is id-based
 * (POST /me/drive/items/{parentId}/children) because POST on the `special/approot` alias returns 400.
 */
export async function ensureFolder(account: AccountInfo, relPath: string): Promise<DriveItem> {
  const token = await getToken(storageScopesFor(account));
  try {
    return await graph<DriveItem>(token, itemPath(account, relPath));
  } catch {
    const parts = relPath.split("/");
    const name = parts.pop()!;
    const parent = parts.length ? await ensureFolder(account, parts.join("/")) : await ensureRoot(account);
    return graph<DriveItem>(token, `/me/drive/items/${parent.id}/children`, {
      method: "POST",
      body: JSON.stringify({ name, folder: {}, "@microsoft.graph.conflictBehavior": "fail" }),
    });
  }
}

export async function putSmallFile(account: AccountInfo, relPath: string, content: string | Blob, contentType = "text/plain"): Promise<DriveItem> {
  const token = await getToken(storageScopesFor(account));
  const res = await fetch(`${GRAPH}${itemPath(account, relPath)}:/content`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": contentType },
    body: content,
  });
  if (!res.ok) throw new Error(`upload ${relPath} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return (await res.json()) as DriveItem;
}

/** A file in the books folder as a Blob (the Review preview). Read-only; straight from the user's OneDrive. */
export async function getFileBlob(account: AccountInfo, relPath: string): Promise<Blob> {
  const token = await getToken(storageScopesFor(account));
  const res = await fetch(`${GRAPH}${itemPath(account, relPath)}:/content`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`read ${relPath} -> ${res.status}`);
  return res.blob();
}

export interface SetupProgress {
  step: string;
  done: number;
  total: number;
}

/** F1: create the folder tree + README. Idempotent. */
export async function setupBooksFolder(account: AccountInfo, onProgress?: (p: SetupProgress) => void): Promise<DriveItem> {
  const total = FOLDERS.length + 2;
  let done = 0;
  onProgress?.({ step: "Finding your Accnomos folder", done, total });
  const root = await ensureRoot(account);
  done++;
  for (const f of FOLDERS) {
    onProgress?.({ step: `Creating ${f}`, done, total });
    await ensureFolder(account, f);
    done++;
  }
  onProgress?.({ step: "Writing README.txt", done, total });
  await putSmallFile(account, "README.txt", README_TEXT);
  onProgress?.({ step: "Done", done: total, total });
  return root;
}
