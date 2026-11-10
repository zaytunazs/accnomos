"use client";

import { googleToken } from "./google";

/**
 * The books folder in Google Drive, from the browser: what lib/graph.ts does over OneDrive, for a Google sign-in.
 * Same rules as the runtime's connector (packages/connectors/src/accnomos_connectors/google_drive.py): the root is
 * `My Drive/Accnomos`, paths are resolved one name at a time, and when a name is duplicated the oldest item wins.
 * The token carries drive.file only, so only items this app made are visible.
 */
const DRIVE = "https://www.googleapis.com/drive/v3";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3";
const FOLDER = "application/vnd.google-apps.folder";
const FIELDS = "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,parents";

/** The shape lib/graph.ts returns (Graph's driveItem fields the app reads). */
export interface GDriveItem {
  id: string;
  name: string;
  webUrl?: string;
  size?: number;
  lastModifiedDateTime?: string;
  folder?: { childCount: number };
  file?: { mimeType: string };
}

interface GFile {
  id: string;
  name: string;
  mimeType: string;
  createdTime?: string;
  size?: string;
  modifiedTime?: string;
  webViewLink?: string;
}

function toItem(f: GFile): GDriveItem {
  const folder = f.mimeType === FOLDER;
  return {
    id: f.id,
    name: f.name,
    webUrl: f.webViewLink,
    size: f.size ? Number(f.size) : undefined,
    lastModifiedDateTime: f.modifiedTime,
    ...(folder ? { folder: { childCount: 0 } } : { file: { mimeType: f.mimeType } }),
  };
}

async function drive<T>(url: string, init: RequestInit = {}): Promise<T> {
  const token = await googleToken();
  const res = await fetch(url, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.headers ?? {}) } });
  if (!res.ok) throw new Error(`Google Drive ${init.method ?? "GET"} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return (await res.json()) as T;
}

const q = (s: string) => `'${s.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;

async function query(clauses: string, orderBy = "createdTime"): Promise<GFile[]> {
  const out: GFile[] = [];
  let pageToken = "";
  do {
    const params = new URLSearchParams({ q: clauses, fields: `nextPageToken,files(${FIELDS})`, orderBy, pageSize: "1000", spaces: "drive" });
    if (pageToken) params.set("pageToken", pageToken);
    const page = await drive<{ files?: GFile[]; nextPageToken?: string }>(`${DRIVE}/files?${params}`);
    out.push(...(page.files ?? []));
    pageToken = page.nextPageToken ?? "";
  } while (pageToken);
  return out;
}

async function child(parentId: string, name: string, want?: "folder" | "file"): Promise<GFile | null> {
  let clauses = `name = ${q(name)} and ${q(parentId)} in parents and trashed = false`;
  if (want === "folder") clauses += ` and mimeType = ${q(FOLDER)}`;
  if (want === "file") clauses += ` and mimeType != ${q(FOLDER)}`;
  return (await query(clauses))[0] ?? null;
}

async function createFolder(parentId: string, name: string): Promise<GFile> {
  return drive<GFile>(`${DRIVE}/files?fields=${FIELDS}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, mimeType: FOLDER, parents: [parentId] }),
  });
}

/**
 * After creating a folder: if another tab or device created the same name first (check-then-create race), ours
 * loses. Whatever was already put in it moves to the winner, ours goes to the bin, and the winner is used: the same
 * rule as the runtime connector, so every reader agrees on one folder.
 */
async function settleFolder(parentId: string, mine: GFile): Promise<GFile> {
  const same = await query(`name = ${q(mine.name)} and ${q(parentId)} in parents and trashed = false and mimeType = ${q(FOLDER)}`);
  const winner = same.sort((a, b) => (a.createdTime ?? "").localeCompare(b.createdTime ?? "") || a.id.localeCompare(b.id))[0];
  if (!winner || winner.id === mine.id) return mine;
  for (const f of await query(`${q(mine.id)} in parents and trashed = false`)) {
    const params = new URLSearchParams({ addParents: winner.id, removeParents: mine.id, fields: "id" });
    await drive(`${DRIVE}/files/${encodeURIComponent(f.id)}?${params}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: "{}" });
  }
  await drive(`${DRIVE}/files/${encodeURIComponent(mine.id)}?fields=id`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trashed: true }),
  });
  return winner;
}

const folders = new Map<string, GFile>(); // books-relative path -> folder, for this page's life

async function root(create: boolean): Promise<GFile | null> {
  const hit = folders.get("");
  if (hit) return hit;
  let f = await child("root", "Accnomos", "folder");
  if (!f && create) f = await settleFolder("root", await createFolder("root", "Accnomos"));
  if (f) folders.set("", f);
  return f;
}

async function folderAt(path: string, create: boolean): Promise<GFile | null> {
  const hit = folders.get(path);
  if (hit) return hit;
  if (!path) return root(create);
  const cut = path.lastIndexOf("/");
  const parent = await folderAt(cut < 0 ? "" : path.slice(0, cut), create);
  if (!parent) return null;
  const name = path.slice(cut + 1);
  let f = await child(parent.id, name, "folder");
  if (!f && create) f = await settleFolder(parent.id, await createFolder(parent.id, name));
  if (f) folders.set(path, f);
  return f;
}

async function fileAt(path: string): Promise<GFile | null> {
  const cut = path.lastIndexOf("/");
  const parent = await folderAt(cut < 0 ? "" : path.slice(0, cut), false);
  if (!parent) return null;
  const name = path.slice(cut + 1);
  return (await child(parent.id, name, "file")) ?? (await child(parent.id, name, "folder"));
}

function notFound(path: string): Error {
  return new Error(`Google Drive: ${path || "the Accnomos folder"} -> 404`);
}

export async function getRoot(): Promise<GDriveItem> {
  const f = await root(false);
  if (!f) throw notFound("");
  return toItem(f);
}

export async function ensureRoot(): Promise<GDriveItem> {
  return toItem((await root(true))!);
}

export async function ensureFolder(relPath: string): Promise<GDriveItem> {
  return toItem((await folderAt(relPath.replace(/^\/+|\/+$/g, ""), true))!);
}

export async function getItem(relPath: string): Promise<GDriveItem> {
  const f = relPath ? await fileAt(relPath) : await root(false);
  if (!f) throw notFound(relPath);
  return toItem(f);
}

export async function listChildren(relPath = ""): Promise<GDriveItem[]> {
  const parent = await folderAt(relPath, false);
  if (!parent) throw notFound(relPath);
  const seen = new Set<string>();
  const out: GDriveItem[] = [];
  for (const f of await query(`${q(parent.id)} in parents and trashed = false`)) {
    const key = `${f.mimeType === FOLDER}:${f.name}`;
    if (seen.has(key)) continue; // a duplicate name: the oldest one is the one paths resolve to
    seen.add(key);
    out.push(toItem(f));
  }
  return out.sort((a, b) => Number(!a.folder) - Number(!b.folder) || a.name.localeCompare(b.name));
}

/** Create or replace a file (multipart upload: metadata and bytes in one request). */
export async function putFile(relPath: string, content: string | Blob, contentType: string): Promise<GDriveItem> {
  const cut = relPath.lastIndexOf("/");
  const parent = (await folderAt(cut < 0 ? "" : relPath.slice(0, cut), true))!;
  const name = relPath.slice(cut + 1);
  const existing = await child(parent.id, name, "file");
  const boundary = `accnomos-${Math.random().toString(36).slice(2)}`;
  const meta = existing ? {} : { name, parents: [parent.id] };
  const body = new Blob([
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n`,
    `--${boundary}\r\nContent-Type: ${contentType}\r\n\r\n`,
    content,
    `\r\n--${boundary}--\r\n`,
  ]);
  const url = existing ? `${UPLOAD}/files/${existing.id}` : `${UPLOAD}/files`;
  const f = await drive<GFile>(`${url}?uploadType=multipart&fields=${FIELDS}`, {
    method: existing ? "PATCH" : "POST",
    headers: { "Content-Type": `multipart/related; boundary=${boundary}` },
    body,
  });
  return toItem(f);
}

export async function getFileBlob(relPath: string): Promise<Blob> {
  const f = await fileAt(relPath);
  if (!f || f.mimeType === FOLDER) throw notFound(relPath);
  const token = await googleToken();
  const res = await fetch(`${DRIVE}/files/${encodeURIComponent(f.id)}?alt=media`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`read ${relPath} -> ${res.status}`);
  return res.blob();
}
