"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeHeaders } from "./runtime";
import { vatQuery } from "./vat-period";

/**
 * "File it yourself" (services/runtime/app/routes_file_yourself.py): the VAT bridging file, the Income Tax quarterly
 * figures and the SA103S / SA103F pages, shown on screen (JSON) and as CSV / XLSX downloads, or saved in 07 Reports.
 */

export type FyKind = "vat" | "itsa-quarterly" | "sa103";
export type FyFormat = "csv" | "xlsx";
export type FyCell = string | number | null;

export interface FySheet {
  kind: string;
  title: string;
  filename: string;
  rows: FyCell[][];
  guidance: string[];
  layout: string[];
  warnings: string[];
  // vat
  quickbooks_csv?: boolean;
  quickbooks_note?: string;
  // itsa-quarterly
  tax_year?: string;
  period_start?: string;
  period_end?: string;
  consolidated_eligible?: boolean;
  // sa103
  form?: "short" | "full";
  suggested_form?: "short" | "full";
  turnover?: number;
}

export interface FySaved {
  path: string;
  name: string;
  size: number;
  web_url: string | null;
  format: string;
}

function query(kind: FyKind, q: Record<string, string | undefined>, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...q, ...extra })) if (v) params.set(k, v);
  const parts = [params.toString()];
  if (kind === "vat") parts.push(vatQuery()); // the saved VAT periods, as /books/vat takes them
  return parts.filter(Boolean).join("&");
}

async function fail(res: Response, what: string): Promise<never> {
  let detail = `${res.status}`;
  try {
    const b = (await res.json()) as { detail?: unknown };
    detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b);
  } catch {
    /* not JSON */
  }
  throw new Error(`Couldn't make the ${what}: ${detail}`);
}

export const fileYourself = {
  preview: async (a: AccountInfo, kind: FyKind, q: Record<string, string | undefined>): Promise<FySheet> => {
    const res = await fetch(`${RUNTIME_URL}/books/file-it-yourself/${kind}?${query(kind, q)}`, { headers: await runtimeHeaders(a) });
    if (!res.ok) return fail(res, "figures");
    return (await res.json()) as FySheet;
  },
  /** Downloads the file in the browser. */
  download: async (a: AccountInfo, kind: FyKind, q: Record<string, string | undefined>, format: FyFormat): Promise<void> => {
    const res = await fetch(`${RUNTIME_URL}/books/file-it-yourself/${kind}?${query(kind, q, { format })}`, { headers: await runtimeHeaders(a) });
    if (!res.ok) return fail(res, format.toUpperCase());
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `${kind}.${format}`;
    const url = URL.createObjectURL(await res.blob());
    const link = Object.assign(document.createElement("a"), { href: url, download: name });
    link.click();
    URL.revokeObjectURL(url);
  },
  /** Saves the file in 07 Reports (never overwriting); audited by the runtime. */
  save: async (a: AccountInfo, kind: FyKind, q: Record<string, string | undefined>, format: FyFormat): Promise<FySaved> => {
    const res = await fetch(`${RUNTIME_URL}/books/file-it-yourself/${kind}/save?${query(kind, q, { format })}`, {
      method: "POST",
      headers: await runtimeHeaders(a),
    });
    if (!res.ok) return fail(res, format.toUpperCase());
    return (await res.json()) as FySaved;
  },
};
