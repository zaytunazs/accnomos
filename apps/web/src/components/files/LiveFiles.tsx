"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import BooksCard from "@/components/files/BooksCard";
import SignInCta from "@/components/SignInCta";
import FilePreview from "@/components/files/FilePreview";
import FileTree from "@/components/files/FileTree";
import FilesTree, {
  OpenLink,
  SYSTEM,
  modified,
  plural,
  size,
  type FilesTreeData,
  type Selection,
} from "@/components/files/FilesTree";
import UploadToInbox from "@/components/review/UploadToInbox";
import { EmptyState, ErrorNote, LoadingSkeleton, RuntimeErrorNote, isAuthError, isServerError } from "@/components/States";
import { FOLDERS } from "@/lib/folders";
import { getRoot, listChildren, type DriveItem } from "@/lib/graph";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, type RtLayout } from "@/lib/runtime";

const ORDER = FOLDERS.filter((f) => !f.includes("/"));

async function loadTree(account: AccountInfo): Promise<FilesTreeData> {
  const [root, top] = await Promise.all([getRoot(account), listChildren(account)]);
  const rank = (name: string) => (ORDER.includes(name) ? ORDER.indexOf(name) : ORDER.length);
  const folderItems = top
    .filter((i) => i.folder && i.name !== SYSTEM)
    .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
  const system = top.find((i) => i.folder && i.name === SYSTEM) ?? null;
  const [folders, systemChildren] = await Promise.all([
    Promise.all(
      folderItems.map(async (item) => {
        const children = item.folder?.childCount ? await listChildren(account, item.name) : [];
        const subfolders = children.filter((c) => c.folder).sort((a, b) => b.name.localeCompare(a.name));
        const directFiles = children.filter((c) => c.file).sort((a, b) => a.name.localeCompare(b.name));
        // A folder's childCount counts folders as well as files, so list each subfolder and count files only.
        const nested = await Promise.all(
          subfolders.map((s) => (s.folder?.childCount ? listChildren(account, `${item.name}/${s.name}`) : Promise.resolve([]))),
        );
        const files = directFiles.length + nested.reduce((n, kids) => n + kids.filter((c) => c.file).length, 0);
        const folders = subfolders.length + nested.reduce((n, kids) => n + kids.filter((c) => c.folder).length, 0);
        return { item, files, folders, subfolders, directFiles };
      }),
    ),
    system ? listChildren(account, SYSTEM) : Promise.resolve([]),
  ]);
  const files = top.filter((i) => i.file).sort((a, b) => a.name.localeCompare(b.name));
  return {
    root,
    folders,
    files,
    all: [...top].sort((a, b) => a.name.localeCompare(b.name)),
    system,
    systemChildren: systemChildren.sort((a, b) => a.name.localeCompare(b.name)),
  };
}

/** The old-named folder and the new one it sits beside, with links to open both. Never a delete. */
function ConflictCard({ layout, all }: { layout: RtLayout; all: DriveItem[] }) {
  const find = (name: string) => all.find((i) => i.name.toLowerCase() === name.toLowerCase());
  return (
    <ErrorNote
      title="Old and new folders side by side"
      body={layout.warning ?? undefined}
      action={
        <ul className="flex list-disc flex-col gap-2 pl-5 text-[14px] leading-6 text-warn-ink">
          {layout.conflicts.map((c) => {
            const oldItem = find(c.old);
            const newItem = find(c.new);
            return (
              <li key={c.old}>
                {c.old} → {c.new}
                {c.old_is_empty ? ": the old folder is empty — nothing to move." : ": move its files into the new folder."}{" "}
                {oldItem?.webUrl && (
                  <a href={oldItem.webUrl} target="_blank" rel="noreferrer" className="font-bold underline underline-offset-2">
                    Open the old folder
                  </a>
                )}
                {oldItem?.webUrl && newItem?.webUrl && " · "}
                {newItem?.webUrl && (
                  <a href={newItem.webUrl} target="_blank" rel="noreferrer" className="font-bold underline underline-offset-2">
                    Open the new folder
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      }
    />
  );
}

function Breadcrumbs({ selection, onSelect }: { selection: Selection; onSelect: (sel: Selection) => void }) {
  const segments = selection ? selection.path.split("/") : [];
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 flex-wrap items-center gap-1 text-[13px] font-semibold">
        <li className="flex min-w-0 items-center gap-1">
          <button
            type="button"
            onClick={() => onSelect(null)}
            aria-current={selection ? undefined : "page"}
            className="shrink-0 rounded-lg px-1 py-0.5 text-teal-dark hover:underline"
          >
            Books
          </button>
        </li>
        {segments.map((seg, i) => {
          const last = i === segments.length - 1;
          const path = segments.slice(0, i + 1).join("/");
          const isFile = last && selection?.kind === "file";
          return (
            <li key={path} className="flex min-w-0 items-center gap-1">
              <span aria-hidden="true" className="shrink-0 text-muted">
                /
              </span>
              {last || isFile ? (
                <span aria-current="page" className="min-w-0 truncate px-1 py-0.5 text-muted">
                  {seg}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onSelect({ kind: "folder", path })}
                  className="min-w-0 truncate rounded-lg px-1 py-0.5 text-teal-dark hover:underline"
                >
                  {seg}
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** A selected folder: what it holds and a way to open it. Files inside are one tap away in the tree. */
function FolderSummary({ tree, path, onClose }: { tree: FilesTreeData; path: string; onClose: () => void }) {
  const [topName, ...rest] = path.split("/");
  const top = tree.folders.find((f) => f.item.name === topName);
  const sub = rest.length > 0 ? top?.subfolders.find((s) => s.name === rest.join("/")) : undefined;
  const item = sub ?? top?.item ?? (path === SYSTEM ? tree.system : undefined) ?? null;
  const count =
    sub && sub.folder
      ? plural(sub.folder.childCount, "item")
      : top
        ? plural(top.files, "file")
        : tree.systemChildren.length > 0 && path === SYSTEM
          ? plural(tree.systemChildren.length, "item")
          : null;
  return (
    <section
      aria-label={`Folder: ${path}`}
      className="flex min-w-0 flex-col gap-3 rounded-2xl border border-border bg-white p-4 sm:p-5"
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-extrabold">{path}</h2>
          <p className="text-[13px] font-medium tabular-nums text-muted">
            {[count, item && size(item.size), item && modified(item.lastModifiedDateTime)].filter(Boolean).join(" · ")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 whitespace-nowrap rounded-xl border border-border px-3 py-1.5 text-[13px] font-bold"
        >
          Close
        </button>
      </div>
      <p className="text-sm text-muted">Pick a file in the tree to preview it here.</p>
      {item && (
        <div className="flex flex-wrap gap-2">
          <OpenLink item={item} />
        </div>
      )}
    </section>
  );
}

/** Files: the user's books folder from Graph when signed in; the sample tree otherwise. Reads only. */
export default function LiveFiles() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [state, setState] = useState<"checking" | "demo" | "loading" | "live" | "missing" | "error">("checking");
  const [tree, setTree] = useState<FilesTreeData | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [layout, setLayout] = useState<RtLayout | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [uploaded, setUploaded] = useState(false);

  const refresh = useCallback(async (acct: AccountInfo) => {
    try {
      // First, so a folder under an old name is renamed before we list the tree. The tree still loads without it.
      setLayout(await runtime.layout(acct).catch(() => null));
      setTree(await loadTree(acct));
      setSelection(null);
      setState("live");
    } catch (e) {
      const msg = (e as Error).message;
      setState(/-> 404/.test(msg) ? "missing" : "error");
      setNote(/-> 404/.test(msg) ? null : msg);
    }
  }, []);

  // /files?path=… (from the audit trail): open the folder that holds it, once the tree is in.
  const [linked, setLinked] = useState(false);
  useEffect(() => {
    if (linked || state !== "live" || !tree) return;
    const path = new URLSearchParams(window.location.search).get("path");
    queueMicrotask(() => {
      setLinked(true);
      if (path) setSelection({ kind: "folder", path: /\.[A-Za-z0-9]{2,5}$/.test(path) ? path.split("/").slice(0, -1).join("/") || path : path });
    });
  }, [linked, state, tree]);

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

  const live = state === "live" && tree;
  const booksFile = tree?.files.find((f) => f.name === "Books.xlsx") ?? null;
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {live && tree.root.webUrl ? (
          <a
            href={tree.root.webUrl}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
          >
            Open in OneDrive
          </a>
        ) : state === "demo" ? (
          <SignInCta />
        ) : null}
      </div>

      {live ? (
        <>
          {layout?.warning && <ConflictCard layout={layout} all={tree.all} />}
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
          <Breadcrumbs selection={selection} onSelect={setSelection} />
          <div className="grid min-w-0 grid-cols-1 items-start gap-3 lg:grid-cols-5">
            <div className="min-w-0 lg:col-span-3">
              <FilesTree tree={tree} account={account!} selection={selection} onSelect={setSelection} />
            </div>
            <div className="min-w-0 lg:col-span-2">
              {!selection && (
                <div className="hidden rounded-2xl border border-border bg-white p-4 sm:p-5 lg:block">
                  <p className="text-[15px] font-extrabold">Preview</p>
                  <p className="mt-1 text-sm text-muted">
                    Pick a file in the tree to see it here — photos and PDFs open directly, JSON and CSV show as text.
                  </p>
                </div>
              )}
            </div>
          </div>
          {selection && (
            <div className="fixed inset-0 z-50 min-w-0 overflow-y-auto bg-white p-3 lg:static lg:z-auto lg:overflow-visible lg:bg-transparent lg:p-0">
              <div className="mx-auto min-w-0 max-w-2xl lg:mx-0 lg:max-w-none">
                {selection.kind === "file" ? (
                  <FilePreview
                    key={selection.path}
                    account={account!}
                    path={selection.path}
                    item={selection.item}
                    onClose={() => setSelection(null)}
                  />
                ) : (
                  <FolderSummary tree={tree} path={selection.path} onClose={() => setSelection(null)} />
                )}
              </div>
            </div>
          )}
          <section aria-label="Add files to 00 Inbox" className="flex min-w-0 flex-col gap-2">
            <h2 className="text-[15px] font-extrabold">Add files</h2>
            <UploadToInbox
              account={account!}
              onDone={() => {
                setUploaded(true);
                void refresh(account!);
              }}
            />
            {uploaded && (
              <p aria-live="polite" className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted">Files are in 00 Inbox.</span>
                <Link
                  href="/review"
                  className="shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2 text-sm font-bold text-white hover:bg-teal-dark"
                >
                  Scan now
                </Link>
              </p>
            )}
          </section>
          <BooksCard account={account!} books={booksFile} onRebuilt={() => account && void refresh(account)} />
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
            <SignInCta className="inline-block whitespace-nowrap rounded-xl bg-teal px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-dark" />
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
          <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] font-medium text-muted">
            <span>{state === "error" ? "Could not read your folder; showing the sample instead." : "Sample folder with fictional files."}</span>
            {state === "demo" && <SignInCta />}
          </p>
          <FileTree />
        </>
      )}
    </div>
  );
}
