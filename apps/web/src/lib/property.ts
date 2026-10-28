"use client";

/**
 * Landlords: the runtime's /property/* (services/runtime/app/routes_property.py) and the relay's UK property
 * routes (services/hmrc-relay/relay/itsa_property.py, HMRC sandbox only). Pence in, pence out; every figure is
 * worked out by the runtime from the approved ledger.
 */
import { useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { accessToken, relay, type ClientFacts, type RelayResult } from "./hmrc";
import { runtimeHeaders } from "./runtime";

/** "Landlord mode" in the menu: mirrors _System/Property/settings.json on this device, so the menu needs no call. */
export const LANDLORD_KEY = "accnomos.landlord.show";
export const LANDLORD_CHANGED = "accnomos:landlord-changed";

export function landlordOn(): boolean {
  try {
    return window.localStorage.getItem(LANDLORD_KEY) === "1";
  } catch {
    return false;
  }
}

export function setLandlordOn(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(LANDLORD_KEY, "1");
    else window.localStorage.removeItem(LANDLORD_KEY);
  } catch {
    /* storage unavailable — the choice lives for this page only */
  }
  window.dispatchEvent(new Event(LANDLORD_CHANGED));
}

/** The Property page is in the menu only while Settings › I let property (landlord mode) is on (this device). */
export function useLandlordOn(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const read = () => setOn(landlordOn());
    queueMicrotask(read);
    window.addEventListener(LANDLORD_CHANGED, read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(LANDLORD_CHANGED, read);
      window.removeEventListener("storage", read);
    };
  }, []);
  return on;
}

export type PropertyUse = "residential" | "commercial" | "rent_a_room";
export type CategoryKey =
  | "rents"
  | "premiums"
  | "reverse_premiums"
  | "other_income"
  | "rent_a_room"
  | "premises"
  | "repairs"
  | "finance_nonres"
  | "professional"
  | "services"
  | "travel"
  | "other"
  | "finance_res"
  | "domestic_items";

export interface RtOwner {
  name: string;
  share_bp: number;
  me: boolean;
}
export interface RtPropertyIn {
  name: string;
  address?: string | null;
  postcode?: string | null;
  use: PropertyUse;
  furnished: boolean;
  holiday_let: boolean;
  joint: "sole" | "spouses" | "other";
  form17: boolean;
  rent_a_room_shared?: boolean;
  owners: RtOwner[];
}
export interface RtProperty extends RtPropertyIn {
  id: string;
  created_at: string;
}
export interface RtPropertyCategory {
  key: CategoryKey;
  label: string;
  group: "income" | "expenses" | "finance" | "annual";
  box: string;
  field: string;
  account: string;
}
export interface RtPropertySettings {
  landlord_mode: boolean;
  quarters: "standard" | "calendar";
  consolidated_expenses: boolean;
  rent_a_room_relief: boolean;
  finance_brought_forward: Record<string, number>;
  business_id: string | null;
}
export interface RtAmounts {
  by_category: Partial<Record<CategoryKey, number>>;
  income: number;
  expenses: number;
  finance_res: number;
  domestic_items: number;
  rent_a_room_rents: number;
  profit: number;
}
export interface RtPropertyFigures {
  property_id: string;
  name: string;
  use: PropertyUse;
  whole: RtAmounts;
  my_share_bp: number;
  mine: RtAmounts;
  owners: { name: string; me: boolean; share_bp: number; income: number; profit: number; finance_res: number }[];
  entries: number;
}
export interface RtPropertySummary {
  tax_year: string;
  start: string;
  end: string;
  basis: string;
  properties: RtPropertyFigures[];
  unallocated: RtAmounts;
  mine: RtAmounts;
  finance: {
    rate_percent: number;
    finance_costs: number;
    brought_forward: number;
    profits_limit: number;
    income_limit: number | null;
    relieved: number;
    credit: number;
    carried_forward: number;
    note: string;
  };
  allowance: { property_allowance_pence: number; gross_income: number; expenses_claimed: number; better: string; note: string };
  rent_a_room_exempt: number;
  warnings: string[];
}
export interface RtPropertyEntry {
  event_id: string;
  date: string;
  property_id: string | null;
  category: CategoryKey | null;
  label: string;
  amount_pence: number;
  side: "income" | "cost";
  description: string | null;
  undone: boolean;
}
export interface RtPropertyEntryIn {
  property_id: string;
  date: string;
  category: CategoryKey;
  amount_pence: number;
  description: string;
  paid_via: "bank" | "cash" | "owner";
  replacing_existing_item?: boolean;
}
export interface RtPropertyMtd {
  tax_year: string;
  period_end: string;
  quarter_ends: string[];
  cumulative: Record<string, unknown>;
  annual: Record<string, unknown>;
  consolidated_allowed: boolean;
  sa105: { box: string; label: string; pence: number }[];
  summary: RtPropertySummary;
}
export interface RtPropertySubmission {
  tax_year: string;
  kind: "cumulative" | "annual";
  period_end: string | null;
  business_id: string;
  sent: Record<string, unknown>;
  status: number;
  correlation_id: string | null;
  at: string;
  by: string;
  matched_books: boolean | null;
}

async function call<T>(account: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const json = typeof init.body === "string";
  const headers = { ...(await runtimeHeaders(account)), ...(json ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch(`${RUNTIME_URL}/property${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail = "";
    try {
      const body = JSON.parse(text) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ") : "";
    } catch {
      /* not JSON */
    }
    throw new Error(detail ? `${detail} (status ${res.status})` : `Could not ${init.method ?? "GET"} /property${path} (${res.status})`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const property = {
  categories: (a: AccountInfo) => call<RtPropertyCategory[]>(a, "/categories"),
  settings: (a: AccountInfo) => call<RtPropertySettings>(a, "/settings"),
  saveSettings: (a: AccountInfo, s: RtPropertySettings) => call<RtPropertySettings>(a, "/settings", put(s)),
  list: (a: AccountInfo) => call<RtProperty[]>(a, "/properties"),
  add: (a: AccountInfo, p: RtPropertyIn) => call<RtProperty>(a, "/properties", post(p)),
  update: (a: AccountInfo, id: string, p: RtPropertyIn) => call<RtProperty>(a, `/properties/${encodeURIComponent(id)}`, put(p)),
  entries: (a: AccountInfo, taxYear: string) => call<RtPropertyEntry[]>(a, `/entries?tax_year=${taxYear}`),
  addEntry: (a: AccountInfo, e: RtPropertyEntryIn) => call<RtPropertyEntry>(a, "/entries", post(e)),
  tag: (a: AccountInfo, eventId: string, propertyId: string) =>
    call<void>(a, `/tags/${encodeURIComponent(eventId)}`, put({ property_id: propertyId })),
  summary: (a: AccountInfo, taxYear: string) => call<RtPropertySummary>(a, `/summary?tax_year=${taxYear}`),
  mtd: (a: AccountInfo, taxYear: string, to?: string) => call<RtPropertyMtd>(a, `/mtd/${taxYear}${to ? `?to=${to}` : ""}`),
  exportFile: (a: AccountInfo, taxYear: string, to: string) =>
    call<{ path: string; name: string; web_url: string | null }>(a, `/mtd/${taxYear}/export`, post({ to })),
  recordSubmission: (a: AccountInfo, s: Omit<RtPropertySubmission, "at" | "by" | "matched_books">) =>
    call<RtPropertySubmission>(a, "/submissions", post({ ...s, sandbox: true })),
  submissions: (a: AccountInfo, taxYear: string) => call<RtPropertySubmission[]>(a, `/submissions?tax_year=${taxYear}`),
};

/** The relay's UK property routes, with the Income Tax HMRC session (sandbox only). */
async function viaRelay<T>(path: string, facts: ClientFacts, extra: Record<string, unknown>): Promise<RelayResult<T>> {
  const body = { client_facts: facts, method: "WEB_APP_VIA_SERVER", ...extra };
  return relay<RelayResult<T>>(path, { method: "POST", body: JSON.stringify(body), token: await accessToken("property") });
}

export const propertyHmrc = {
  businesses: (nino: string, facts: ClientFacts) =>
    viaRelay<{ listOfBusinesses?: { typeOfBusiness: string; businessId: string }[] }>(`/itsa/${nino}/property/businesses`, facts, {}),
  submitCumulative: (nino: string, businessId: string, taxYear: string, facts: ClientFacts, summary: Record<string, unknown>) =>
    viaRelay<null>(`/itsa/${nino}/property/${businessId}/cumulative/${taxYear}`, facts, { summary, confirmed: true }),
  createTestBusiness: (nino: string, taxYear: string, facts: ClientFacts) =>
    viaRelay<{ businessId?: string }>(`/itsa/${nino}/property/test-business`, facts, { tax_year: taxYear }),
};

export const NINO_RE = /^[A-Z]{2}\d{6}[A-D]$/;
export const BUSINESS_ID_RE = /^X[A-Z0-9]IS\d{11}$/;

/** "2026-27" for a London date like "2026-10-28". */
export function taxYearOf(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const start = m > 4 || (m === 4 && d >= 6) ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}
