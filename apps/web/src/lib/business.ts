"use client";

/**
 * The user's business details (onboarding step 3). Lives only on this device
 * (localStorage) — the static export has no server to store it on.
 */

export type VatPeriod = "quarterly" | "monthly" | "annual";

export type PeriodEnd = "Mar/Jun/Sep/Dec" | "Jan/Apr/Jul/Oct" | "Feb/May/Aug/Nov";

/** HMRC stagger group for quarterly returns, or a custom month in which a quarter starts. */
export type Stagger = "1" | "2" | "3" | "custom";

export interface Business {
  name: string;
  vatNumber: string;
  /** False when "I'm not VAT-registered" was ticked: VAT steps stay hidden. */
  vatRegistered: boolean;
  vatPeriod: VatPeriod;
  periodEnd: PeriodEnd; // kept in step with `stagger` for older readers
  stagger: Stagger;
  customStartMonth: number; // 1-12, used when stagger is "custom"
  flatRate: boolean;
  email: string;
  workStart: string; // "HH:MM", the day planner's default working hours
  workEnd: string;
  maxVisits: number;
}

const KEY = "accnomos.business";

export const STAGGER_OPTIONS: { value: Stagger; label: string; periodEnd?: PeriodEnd }[] = [
  { value: "1", label: "Stagger 1 — periods end Mar, Jun, Sep, Dec", periodEnd: "Mar/Jun/Sep/Dec" },
  { value: "2", label: "Stagger 2 — periods end Apr, Jul, Oct, Jan", periodEnd: "Jan/Apr/Jul/Oct" },
  { value: "3", label: "Stagger 3 — periods end May, Aug, Nov, Feb", periodEnd: "Feb/May/Aug/Nov" },
  { value: "custom", label: "Custom — choose the month a period starts" },
];

export const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export const DEFAULT_BUSINESS: Business = {
  name: "",
  vatNumber: "",
  vatRegistered: true,
  vatPeriod: "quarterly",
  periodEnd: "Mar/Jun/Sep/Dec",
  stagger: "1",
  customStartMonth: 1,
  flatRate: false,
  email: "",
  workStart: "08:00",
  workEnd: "17:30",
  maxVisits: 5,
};

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export function loadBusiness(): Business | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Business>;
    // Saved before the stagger setting existed: derive it from the period-end choice.
    const stagger = parsed.stagger ?? STAGGER_OPTIONS.find((o) => o.periodEnd === parsed.periodEnd)?.value ?? "1";
    const month = Number(parsed.customStartMonth);
    const visits = Number(parsed.maxVisits);
    const start = HHMM.test(parsed.workStart ?? "") ? parsed.workStart! : DEFAULT_BUSINESS.workStart;
    const end = HHMM.test(parsed.workEnd ?? "") ? parsed.workEnd! : DEFAULT_BUSINESS.workEnd;
    return {
      ...DEFAULT_BUSINESS,
      ...parsed,
      vatRegistered: parsed.vatRegistered !== false,
      stagger,
      customStartMonth: month >= 1 && month <= 12 ? month : 1,
      flatRate: parsed.flatRate === true,
      workStart: start < end ? start : DEFAULT_BUSINESS.workStart,
      workEnd: start < end ? end : DEFAULT_BUSINESS.workEnd,
      maxVisits: visits >= 1 && visits <= 12 ? Math.round(visits) : DEFAULT_BUSINESS.maxVisits,
    };
  } catch {
    return null;
  }
}

/** Query string for GET /books/deadlines and the other VAT routes (`stagger=2`, `start_month=5`, `months=1`). */
export function deadlinesQuery(b: Business | null): string | null {
  const business = b ?? DEFAULT_BUSINESS;
  // Annual: the quarters before and after the annual periods; the annual periods themselves come from the VAT
  // scheme saved in the books (Settings › VAT scheme), so the runtime can work them out.
  if (business.vatPeriod === "monthly") return "months=1";
  return business.stagger === "custom" ? `start_month=${business.customStartMonth}` : `stagger=${business.stagger}`;
}

export interface PlanVat {
  stagger?: number;
  start_month?: number;
  months: 1 | 3;
}

/** VAT periods for POST /plan/day (admin time when a return is due), or null when not worked out (annual). */
export function planVat(b: Business | null): PlanVat | null {
  const business = b ?? DEFAULT_BUSINESS;
  if (business.vatPeriod === "annual") return null;
  if (business.vatPeriod === "monthly") return { months: 1 };
  return business.stagger === "custom"
    ? { start_month: business.customStartMonth, months: 3 }
    : { stagger: Number(business.stagger), months: 3 };
}

export function saveBusiness(business: Business): void {
  const periodEnd = STAGGER_OPTIONS.find((o) => o.value === business.stagger)?.periodEnd ?? business.periodEnd;
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...business, periodEnd }));
  } catch {
    /* storage unavailable (private mode) — business lives for this page only */
  }
}

/**
 * Validate a UK VAT number. Spaces are ignored, the GB prefix is optional
 * except for the government/health variants. Valid shapes:
 * GB + 9 digits, GB + 12 digits, GBGD + 3 digits, GBHA + 3 digits.
 * Returns an error message, or null when valid (empty counts as invalid).
 */
export function validateVatNumber(raw: string): string | null {
  const compact = raw.replace(/\s+/g, "").toUpperCase();
  if (!compact) return "Enter your VAT number.";
  if (/^(GB)?\d{9}$/.test(compact)) return null;
  if (/^(GB)?\d{12}$/.test(compact)) return null;
  if (/^GBGD\d{3}$/.test(compact)) return null;
  if (/^GBHA\d{3}$/.test(compact)) return null;
  return "Check the format — e.g. GB 123 4567 89.";
}
