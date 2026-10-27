"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import FileTree, { FileIcon, FolderIcon } from "@/components/files/FileTree";
import { EmptyState, ErrorNote, LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { FOLDER, FOLDERS } from "@/lib/folders";
import { getRoot, listChildren, type DriveItem } from "@/lib/graph";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, type RtLayout } from "@/lib/runtime";

const SYSTEM = "_System";
const NEEDS_A_LOOK = FOLDER.needs_a_look;
const ORDER = FOLDERS.filter((f) => !f.includes("/"));

interface FolderRow {
  item: DriveItem;
  files: number; // files directly inside plus files one level down (e.g. 01 Receipts/2026-10)
  subfolders: DriveItem[];
}

interface Tree {
  root: DriveItem;
  folders: FolderRow[];
  files: DriveItem[];
  system: DriveItem | null;
  systemChildren: DriveItem[];
}

function size(bytes?: number): string {
  if (bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024).toLocaleString("en-GB")} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} MB`;
}

function modified(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

async function loadTree(account: AccountInfo): Promise<Tree> {
  const [root, top] = await Promise.all([getRoot(account), listChildren(account)]);
  const rank = (name: string) => (ORDER.includes(name) ? ORDER.indexOf(name) : ORDER.length);
  const folderItems = top
    .filter((i) => i.folder && i.name !== SYSTEM)
    .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
  const system = top.find((i) => i.folder && i.name === SYSTEM) ?? null;
  const [folders, systemChildren] = await Promise.all([
    Promise.all(
      folderItems.map(async (item): Promise<FolderRow> => {
        const children = item.folder?.childCount ? await listChildren(account, item.name) : [];
        const subfolders = children.filter((c) => c.folder).sort((a, b) => b.name.localeCompare(a.name));
        const files = children.filter((c) => c.file).length + subfolders.reduce((n, s) => n + (s.folder?.childCount ?? 0), 0);
        return { item, files, subfolders };
      }),
    ),
    system ? listChildren(account, SYSTEM) : Promise.resolve([]),
  ]);
  const files = top.filter((i) => i.file).sort((a, b) => a.name.localeCompare(b.name));
  return { root, folders, files, system, systemChildren: systemChildren.sort((a, b) => a.name.localeCompare(b.name)) };
}

function OpenLink({ item, label = "Open in OneDrive" }: { item: DriveItem; label?: string }) {
  if (!item.webUrl) return null;
  return (
    <a
      href={item.webUrl}
      target="_blank"
      rel="noreferrer"
      className="shrink-0 text-[13px] font-bold text-teal-dark hover:underline"
      aria-label={`${label}: ${item.name}`}
    >
      {label}
    </a>
  );
}

function Meta({ item, count }: { item: DriveItem; count?: string }) {
  return (
    <span className="flex shrink-0 flex-wrap items-center justify-end gap-x-3 text-[13px] font-medium tabular-nums text-muted">
      {count !== undefined && <span>{count}</span>}
      <span>{size(item.size)}</span>
      <span className="hidden min-[560px]:inline">{modified(item.lastModifiedDateTime)}</span>
    </span>
  );
}

const row = "flex min-h-[44px] items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0";

function LiveTree({ tree }: { tree: Tree }) {
  return (
    <ul className="flex flex-col overflow-hidden rounded-2xl border border-border bg-white">
      {tree.folders.map(({ item, files, subfolders }) => (
        <li key={item.id} className="border-b border-border last:border-b-0">
          <div className={row}>
            <FolderIcon />
            <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">{item.name}</span>
            {item.name === NEEDS_A_LOOK && files > 0 ? (
              <span className="rounded-full border border-warn-border bg-warn-bg px-2.5 py-0.5 text-[13px] font-bold text-warn-ink">
                {plural(files, "file")}
              </span>
            ) : null}
            <Meta item={item} count={item.name === NEEDS_A_LOOK && files > 0 ? undefined : plural(files, "file")} />
            <OpenLink item={item} label="Open" />
          </div>
          {subfolders.length > 0 && (
            <ul>
              {subfolders.map((s) => (
                <li key={s.id} className={`${row} pl-11`}>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-muted">› {s.name}</span>
                  <Meta item={s} count={plural(s.folder?.childCount ?? 0, "item")} />
                  <OpenLink item={s} label="Open" />
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
      {tree.files.map((f) => (
        <li key={f.id} className={row}>
          <FileIcon />
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">{f.name}</span>
          <Meta item={f} />
          <OpenLink item={f} label="Open" />
        </li>
      ))}
      {tree.system && (
        <li className="relative border-b border-border last:border-b-0">
          <details>
            {/* The Open link sits beside the summary, not in it: no link inside the disclosure button. */}
            <summary className={`${row} cursor-pointer list-none border-b-0 ${tree.system.webUrl ? "pr-16" : ""}`}>
              <FolderIcon />
              <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">
                {SYSTEM}
                <span className="ml-2 text-[13px] font-medium text-muted">rules, audit log, ledger events · show</span>
              </span>
              <Meta item={tree.system} />
            </summary>
            <ul className="border-t border-border">
              {tree.systemChildren.map((c) => (
                <li key={c.id} className={`${row} pl-11`}>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-muted">{c.name}</span>
                  <Meta item={c} count={c.folder ? plural(c.folder.childCount, "item") : undefined} />
                  <OpenLink item={c} label="Open" />
                </li>
              ))}
            </ul>
          </details>
          <span className="absolute right-4 top-0 flex min-h-[44px] items-center">
            <OpenLink item={tree.system} label="Open" />
          </span>
        </li>
      )}
    </ul>
  );
}

/** Files: the user's books folder from Graph when signed in; the sample tree otherwise. Reads only. */
export default function LiveFiles() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "missing" | "error">("checking");
  const [tree, setTree] = useState<Tree | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [layout, setLayout] = useState<RtLayout | null>(null);

  const refresh = useCallback(async (acct: AccountInfo) => {
    try {
      // First, so a folder under an old name is renamed before we list the tree. The tree still loads without it.
      setLayout(await runtime.layout(acct).catch(() => null));
      setTree(await loadTree(acct));
      setState("live");
    } catch (e) {
      const msg = (e as Error).message;
      setState(/-> 404/.test(msg) ? "missing" : "error");
      setNote(/-> 404/.test(msg) ? null : msg);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (!msalConfigured()) return setState("demo");
        const msal = await getMsal();
        await msal.handleRedirectPromise().catch(() => null);
        const acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        if (!acct) return setState("demo");
        setAccount(acct);
        setState("loading");
        await refresh(acct);
      } catch {
        setState("demo");
      }
    })();
  }, [refresh]);

  async function rebuild() {
    if (!account) return;
    setRebuilding(true);
    setNote(null);
    try {
      const r = await runtime.rebuild(account);
      setNote(`Books.xlsx rebuilt from your ledger events · ${size(r.size)}`);
      await refresh(account);
    } catch (e) {
      setNote(`Could not rebuild Books.xlsx: ${(e as Error).message}`);
    } finally {
      setRebuilding(false);
    }
  }

  const live = state === "live" && tree;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={rebuild}
          disabled={!account || rebuilding || state === "missing"}
          title={account ? "Regenerate Books.xlsx from the ledger event files" : "Connect your OneDrive to rebuild"}
          className="shrink-0 whitespace-nowrap rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark disabled:border-border disabled:text-muted"
        >
          {rebuilding ? "Rebuilding…" : "Rebuild Books.xlsx"}
        </button>
        {live && tree.root.webUrl ? (
          <a
            href={tree.root.webUrl}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
          >
            Open in OneDrive
          </a>
        ) : (
          <Link
            href={state === "demo" ? "/connect" : "#"}
            className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
          >
            {state === "demo" ? "Connect your OneDrive" : "Open in OneDrive"}
          </Link>
        )}
      </div>

      {note && (
        <p role="status" className="text-sm font-semibold text-teal-dark">
          {note}
        </p>
      )}

      {live ? (
        <>
          {layout?.warning && (
            <ErrorNote
              title="Old and new folders side by side"
              body={layout.warning}
              action={
                <ul className="list-disc pl-5 text-[14px] leading-6 text-warn-ink">
                  {layout.conflicts.map((c) => (
                    <li key={c.old}>
                      {c.old} → {c.new}
                      {c.old_is_empty ? ": the old folder is empty, so you can delete it." : ": move its files into the new folder."}
                    </li>
                  ))}
                </ul>
              }
            />
          )}
          {tree.folders.reduce((n, f) => n + f.files, tree.files.length) === 0 && (
            <EmptyState
              title="Your folder is empty"
              body="Receipts, statements and your Books.xlsx appear here once you add and approve your first documents."
              action={
                <Link
                  href="/review"
                  className="inline-flex h-11 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
                >
                  Add a receipt
                </Link>
              }
            />
          )}
          <LiveTree tree={tree} />
          <p className="text-[13px] font-medium text-muted">
            {plural(tree.folders.reduce((n, f) => n + f.files, tree.files.length), "file")} outside _System · {size(tree.root.size)} in
            total. Books.xlsx is generated from _System/Ledger/events; edits to it are overwritten.
          </p>
        </>
      ) : state === "missing" ? (
        <EmptyState
          title="Folder not set up yet"
          body="Your Accnomos folder in OneDrive hasn't been created."
          action={
            <Link
              href="/connect"
              className="inline-block whitespace-nowrap rounded-xl bg-teal px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
            >
              Finish connecting
            </Link>
          }
        />
      ) : state === "checking" || state === "loading" ? (
        <LoadingSkeleton
          lines={4}
          label={state === "loading" ? "Reading your books folder…" : "Checking sign-in…"}
        />
      ) : (
        <>
          {state === "error" && (
            note && (isAuthError(note) || isServerError(note)) ? (
              <RuntimeErrorNote message={note} title="Couldn't read your folder" />
            ) : (
              <ErrorNote
                title="Couldn't read your folder"
                body={note ? `${note} Showing the sample instead.` : "Showing the sample instead."}
              />
            )
          )}
          <p className="text-[13px] font-medium text-muted">
            {state === "error" ? "Could not read your folder; showing the sample instead. " : "Sample folder. "}
            SAMPLE — FICTIONAL COMPANY
          </p>
          <FileTree />
        </>
      )}
    </div>
  );
}
