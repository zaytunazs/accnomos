"use client";

import { useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { FileIcon, FolderIcon } from "@/components/files/FileTree";
import { FOLDER } from "@/lib/folders";
import { listChildren, type DriveItem } from "@/lib/graph";

export const SYSTEM = "_System";

export interface FolderRow {
  item: DriveItem;
  files: number; // files directly inside plus files one level down (e.g. 01 Receipts/2026-10)
  subfolders: DriveItem[];
}

export interface FilesTreeData {
  root: DriveItem;
  folders: FolderRow[];
  files: DriveItem[];
  all: DriveItem[]; // every top-level child, for resolving old/new folder links
  system: DriveItem | null;
  systemChildren: DriveItem[];
}

export type Selection = { kind: "file"; path: string; item: DriveItem } | { kind: "folder"; path: string } | null;

export interface NavProps {
  "data-treenav": string;
  "data-node": "folder" | "file";
  "data-parent"?: string;
  "data-expanded"?: string;
  "aria-expanded"?: boolean;
  tabIndex: number;
  onFocus: () => void;
}

export function size(bytes?: number): string {
  if (bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024).toLocaleString("en-GB")} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString("en-GB", { maximumFractionDigits: 1 })} MB`;
}

export function modified(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

export function OpenLink({ item, label = "Open in OneDrive" }: { item: DriveItem; label?: string }) {
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
    <span className="flex min-w-0 flex-wrap items-center gap-x-3 text-[13px] font-medium tabular-nums text-muted">
      {count !== undefined && <span>{count}</span>}
      <span>{size(item.size)}</span>
      <span>{modified(item.lastModifiedDateTime)}</span>
    </span>
  );
}

const row = "flex min-h-[44px] flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2.5 last:border-b-0";

export default function FilesTree({
  tree,
  account,
  selection,
  onSelect,
}: {
  tree: FilesTreeData;
  account: AccountInfo;
  selection: Selection;
  onSelect: (sel: Selection) => void;
}) {
  // Collapsed node ids. Top-level folders start expanded; _System and every subfolder start collapsed.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set([SYSTEM]));
  const [kids, setKids] = useState<Record<string, DriveItem[] | null>>({});
  const [kidError, setKidError] = useState<Record<string, string>>({});
  const [tabbed, setTabbed] = useState<string | null>(null);

  function toggle(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function expandSubfolder(parent: string, sub: DriveItem) {
    const id = `${parent}/${sub.name}`;
    const opening = collapsed.has(id);
    toggle(id);
    if (opening && kids[id] === undefined) {
      try {
        const children = await listChildren(account, id);
        setKids((prev) => ({
          ...prev,
          [id]: [...children.filter((c) => c.folder), ...children.filter((c) => !c.folder)].sort((a, b) =>
            a.folder && !b.folder ? -1 : !a.folder && b.folder ? 1 : a.name.localeCompare(b.name),
          ),
        }));
      } catch (e) {
        setKidError((prev) => ({ ...prev, [id]: (e as Error).message }));
        setKids((prev) => ({ ...prev, [id]: null }));
      }
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLUListElement>) {
    const el = e.currentTarget;
    if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    const buttons = Array.from(el.querySelectorAll<HTMLButtonElement>("button[data-treenav]"));
    const active = document.activeElement as HTMLElement | null;
    const i = buttons.indexOf(active as HTMLButtonElement);
    if (i === -1) return;
    e.preventDefault();
    if (e.key === "ArrowDown") {
      const next = buttons[i + 1];
      if (next) next.focus();
    } else if (e.key === "ArrowUp") {
      const prev = buttons[i - 1];
      if (prev) prev.focus();
      else el.querySelector<HTMLButtonElement>("button[data-treenav]")?.focus();
    } else if (e.key === "Home") {
      buttons[0]?.focus();
    } else if (e.key === "End") {
      buttons[buttons.length - 1]?.focus();
    } else if (e.key === "ArrowRight") {
      const id = active?.dataset.treenav;
      if (id && active?.dataset.node === "folder" && active?.dataset.expanded === "false") {
        (active as HTMLButtonElement).click();
      }
    } else if (e.key === "ArrowLeft") {
      const id = active?.dataset.treenav;
      if (id && active?.dataset.node === "folder" && active?.dataset.expanded === "true") {
        (active as HTMLButtonElement).click();
      } else {
        const parent = active?.dataset.parent;
        if (parent) el.querySelector<HTMLButtonElement>(`button[data-treenav="${CSS.escape(parent)}"]`)?.focus();
      }
    }
  }

  function navProps(id: string, node: "folder" | "file", parent?: string, expanded?: boolean): NavProps {
    return {
      "data-treenav": id,
      "data-node": node,
      ...(parent ? { "data-parent": parent } : {}),
      ...(node === "folder" ? { "data-expanded": expanded ? "true" : "false", "aria-expanded": expanded } : {}),
      tabIndex: tabbed === null ? (id === firstId ? 0 : -1) : tabbed === id ? 0 : -1,
      onFocus: () => setTabbed(id),
    };
  }

  const firstId = tree.folders[0]?.item.name ?? tree.files[0]?.name ?? SYSTEM;

  function folderButton(id: string, name: string, item: DriveItem, count: React.ReactNode, onToggle: () => void, parent?: string, expanded?: boolean, indent = false) {
    const selected = selection?.kind === "folder" && selection.path === id;
    return (
      <div className={row}>
        <button
          type="button"
          {...navProps(id, "folder", parent, expanded)}
          aria-current={selected ? "true" : undefined}
          onClick={() => {
            onToggle();
            onSelect({ kind: "folder", path: id });
          }}
          className={`flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left ${indent ? "pl-7" : ""}`}
        >
          <FolderIcon />
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">{name}</span>
          {count}
        </button>
        <Meta item={item} />
        <OpenLink item={item} label="Open" />
      </div>
    );
  }

  return (
    <ul
      onKeyDown={onKeyDown}
      aria-label="Books folders"
      className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-white"
    >
      {tree.folders.map(({ item, files, subfolders }) => {
        const id = item.name;
        const open = !collapsed.has(id);
        return (
          <li key={item.id} className="border-b border-border last:border-b-0">
            {folderButton(
              id,
              item.name,
              item,
              item.name === FOLDER.needs_a_look && files > 0 ? (
                <span className="rounded-full border border-warn-border bg-warn-bg px-2.5 py-0.5 text-[13px] font-bold text-warn-ink">
                  {plural(files, "file")}
                </span>
              ) : (
                <span className="shrink-0 text-[13px] font-medium tabular-nums text-muted">{plural(files, "file")}</span>
              ),
              () => toggle(id),
              undefined,
              open,
            )}
            {open && subfolders.length > 0 && (
              <ul aria-label={`${item.name}: subfolders`}>
                {subfolders.map((s) => {
                  const subId = `${item.name}/${s.name}`;
                  const subOpen = !collapsed.has(subId);
                  return (
                    <li key={s.id} className="border-t border-border">
                      <div className={`${row} pl-4`}>
                        <button
                          type="button"
                          {...navProps(subId, "folder", id, subOpen)}
                          aria-current={selection?.kind === "folder" && selection.path === subId ? "true" : undefined}
                          onClick={() => {
                            void expandSubfolder(item.name, s);
                            onSelect({ kind: "folder", path: subId });
                          }}
                          className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left"
                        >
                          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-muted">› {s.name}</span>
                          <span className="shrink-0 text-[13px] font-medium tabular-nums text-muted">
                            {plural(s.folder?.childCount ?? 0, "item")}
                          </span>
                        </button>
                        <Meta item={s} />
                        <OpenLink item={s} label="Open" />
                      </div>
                      {subOpen && (
                        <ul aria-label={`${subId}: files`}>
                          {kids[subId] === undefined ? (
                            <li className={`${row} pl-11`}>
                              <span role="status" className="text-sm text-muted">
                                Reading {s.name}…
                              </span>
                            </li>
                          ) : kidError[subId] ? (
                            <li className={`${row} pl-11`}>
                              <span role="alert" className="text-sm font-semibold text-warn-ink">
                                Could not read {s.name}: {kidError[subId]}
                              </span>
                            </li>
                          ) : (
                            (kids[subId] ?? []).map((f) =>
                              f.folder ? (
                                <li key={f.id} className={`${row} border-t border-border pl-11`}>
                                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-muted">
                                    › {f.name}
                                  </span>
                                  <Meta item={f} count={plural(f.folder.childCount, "item")} />
                                  <OpenLink item={f} label="Open" />
                                </li>
                              ) : (
                                <FileRow
                                  key={f.id}
                                  item={f}
                                  relPath={subId}
                                  nav={navProps(`f:${subId}/${f.name}`, "file", subId)}
                                  selected={selection?.kind === "file" && selection.path === `${subId}/${f.name}`}
                                  onSelect={onSelect}
                                />
                              ),
                            )
                          )}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        );
      })}
      {tree.files.map((f) => (
        <FileRow
          key={f.id}
          item={f}
          relPath=""
          nav={navProps(`f:${f.name}`, "file")}
          selected={selection?.kind === "file" && selection.path === f.name}
          onSelect={onSelect}
        />
      ))}
      {tree.system && (
        <li className="border-b border-border last:border-b-0">
          <div className={row}>
            <button
              type="button"
              {...navProps(SYSTEM, "folder", undefined, !collapsed.has(SYSTEM))}
              onClick={() => toggle(SYSTEM)}
              className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left"
            >
              <FolderIcon />
              <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">
                {SYSTEM}
                <span className="ml-2 text-[13px] font-medium text-muted">rules, audit log, ledger events · show</span>
              </span>
            </button>
            <Meta item={tree.system} />
            <OpenLink item={tree.system} label="Open" />
          </div>
          {!collapsed.has(SYSTEM) && (
            <ul aria-label="_System: contents" className="border-t border-border">
              {tree.systemChildren.map((c) => (
                <li key={c.id} className={`${row} pl-11`}>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-muted">{c.name}</span>
                  <Meta item={c} count={c.folder ? plural(c.folder.childCount, "item") : undefined} />
                  <OpenLink item={c} label="Open" />
                </li>
              ))}
            </ul>
          )}
        </li>
      )}
    </ul>
  );
}

function FileRow({
  item,
  relPath,
  nav,
  selected,
  onSelect,
}: {
  item: DriveItem;
  relPath: string;
  nav: NavProps;
  selected: boolean;
  onSelect: (sel: Selection) => void;
}) {
  const path = relPath ? `${relPath}/${item.name}` : item.name;
  return (
    <li className="border-b border-border last:border-b-0">
      <div className={`${row} pl-11`}>
        <button
          type="button"
          {...nav}
          aria-current={selected ? "true" : undefined}
          onClick={() => onSelect({ kind: "file", path, item })}
          className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left"
        >
          <FileIcon />
          <span className="min-w-0 flex-1 truncate text-[15px] font-semibold">{item.name}</span>
        </button>
        <Meta item={item} />
        <OpenLink item={item} label="Open" />
      </div>
    </li>
  );
}
