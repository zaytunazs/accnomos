"use client";

import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeHeaders } from "./runtime";

/**
 * Goals (services/runtime/app/goals.py, routes_goals.py): targets the owner sets for the business or the household,
 * tracked by code against their own books. Money is whole pence. The runtime works out every figure, the status and
 * code's suggestions; the user's AI (same headers as Home's summary) only words the note, and code checks it.
 */

export type GoalKind = "save" | "spend_cap" | "spend_less" | "earn";
export type GoalStatus =
  | "not_started"
  | "just_started"
  | "on_track"
  | "at_risk"
  | "off_track"
  | "reached"
  | "missed"
  | "over_limit"
  | "no_data";
export type GoalTone = "positive" | "warning" | "negative" | "neutral";

export interface RtGoalIn {
  name: string;
  kind: GoalKind;
  start: string; // YYYY-MM-DD
  end: string;
  target_pence?: number | null;
  percent?: number | null;
  focus?: string | null;
  measure?: "manual" | "net_cash";
  saved_pence?: number;
  note?: string | null;
}

export interface RtGoal extends RtGoalIn {
  id: string;
  scope: "business" | "personal" | null;
  created_at: string;
  created_by?: string | null;
  measure: "manual" | "net_cash";
  saved_pence: number;
}

export interface RtGoalDriver {
  name: string;
  kind: "category" | "item" | "supplier";
  this_pence: number;
  before_pence: number;
  change_pence: number;
}

export interface RtGoalProgress {
  goal: RtGoal;
  kind_label: string;
  status: GoalStatus;
  status_label: string;
  tone: GoalTone;
  period_label: string;
  current_pence: number;
  target_pence: number | null;
  target_label: string;
  baseline_pence?: number | null;
  baseline_label?: string | null;
  plan_to_date_pence: number | null;
  percent: number | null;
  variance_pence: number | null;
  variance_text: string;
  needed_text?: string | null;
  run_rate_pence?: number | null;
  days_left: number;
  as_of: string | null;
  source_text: string;
  drivers: RtGoalDriver[];
  suggestions: string[];
}

export interface RtGoalsNote {
  note_md: string;
  model: string; // "code" when no AI is set up
  fallback_reason?: string | null;
}

export interface RtGoalsView {
  today: string;
  household: boolean;
  goals: RtGoalProgress[];
  note: RtGoalsNote;
  facts: Record<string, unknown>;
  /** Set only on the signed-out sample (lib/sample-goals.ts). */
  sample?: boolean;
}

/** The runtime's refusal as one plain sentence (FastAPI's 422 list, or its `detail` string). */
async function refusal(res: Response, what: string): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return `${body.detail} (status ${res.status})`;
    if (Array.isArray(body.detail) && body.detail.length) {
      const first = body.detail[0] as { msg?: string };
      const msg = String(first.msg ?? "").replace(/^Value error, /, "");
      if (msg) return `${msg.charAt(0).toUpperCase()}${msg.slice(1)} (status ${res.status})`;
    }
  } catch {
    /* not JSON */
  }
  return `Could not ${what} (${res.status})`;
}

async function call<T>(account: AccountInfo, path: string, init: RequestInit = {}): Promise<T> {
  const headers = {
    ...(await runtimeHeaders(account)),
    ...(typeof init.body === "string" ? { "Content-Type": "application/json" } : {}),
  };
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers });
  if (!res.ok) throw new Error(await refusal(res, `${(init.method ?? "GET").toLowerCase()} the goals`));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const goalsApi = {
  /** `noteAi` false: code writes the note (fast); true: the user's AI words it (slow). Pages load the fast one first. */
  list: (a: AccountInfo, today: string, noteAi = true) =>
    call<RtGoalsView>(a, `/books/goals?today=${today}${noteAi ? "" : "&note_ai=false"}`),
  add: (a: AccountInfo, g: RtGoalIn) => call<RtGoal>(a, "/books/goals", { method: "POST", body: JSON.stringify(g) }),
  patch: (a: AccountInfo, id: string, patch: Partial<RtGoalIn>) =>
    call<RtGoal>(a, `/books/goals/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }),
  remove: (a: AccountInfo, id: string) =>
    call<void>(a, `/books/goals/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

/** "Strip the (status 422)" tail for showing a refusal next to the form. */
export const plainError = (e: unknown) =>
  String((e as Error)?.message ?? e)
    .replace(/\s*\(status \d+[^)]*\)\s*$/, "")
    .trim();

/** Most urgent first: off track, over the limit or missed; then at risk; then the rest in the order saved. */
const URGENCY: Record<GoalStatus, number> = {
  off_track: 0,
  over_limit: 0,
  missed: 0,
  at_risk: 1,
  on_track: 2,
  just_started: 3,
  no_data: 3,
  not_started: 4,
  reached: 5,
};
export function byUrgency(goals: RtGoalProgress[]): RtGoalProgress[] {
  return goals
    .map((g, i) => [g, i] as const)
    .sort((a, b) => URGENCY[a[0].status] - URGENCY[b[0].status] || a[1] - b[1])
    .map(([g]) => g);
}

/** "£1,234.56" from pence; a minus in front for a negative amount. */
export function money(pence: number | null | undefined): string {
  if (pence === null || pence === undefined) return "—";
  const p = Math.abs(pence);
  return `${pence < 0 ? "-" : ""}£${Math.floor(p / 100).toLocaleString("en-GB")}.${String(p % 100).padStart(2, "0")}`;
}

/** "£37,500" for a large figure, with pence only when there are any. */
export function headline(pence: number): string {
  return pence % 100 === 0 ? `${pence < 0 ? "-" : ""}£${Math.abs(pence / 100).toLocaleString("en-GB")}` : money(pence);
}
