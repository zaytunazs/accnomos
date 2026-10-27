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
  vatPeriod: VatPeriod;
  periodEnd: PeriodEnd; // kept in step with `stagger` for older readers
  stagger: Stagger;
  customStartMonth: number; // 1-12, used when stagger is "custom"
  flatRate: boolean;
  email: string;
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
  vatPeriod: "quarterly",
  periodEnd: "Mar/Jun/Sep/Dec",
  stagger: "1",
  customStartMonth: 1,
  flatRate: false,
  email: "",
};

export function loadBusiness(): Business | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Business>;
    // Saved before the stagger setting existed: derive it from the period-end choice.
    const stagger = parsed.stagger ?? STAGGER_OPTIONS.find((o) => o.periodEnd === parsed.periodEnd)?.value ?? "1";
    const month = Number(parsed.customStartMonth);
    return {
      ...DEFAULT_BUSINESS,
      ...parsed,
      stagger,
      customStartMonth: month >= 1 && month <= 12 ? month : 1,
      flatRate: parsed.flatRate === true,
    };
  } catch {
    return null;
  }
}

/**
 * Query string for GET /books/deadlines, or null when the runtime cannot work the deadlines out
 * (annual accounting has different rules).
 */
export function deadlinesQuery(b: Business | null): string | null {
  const business = b ?? DEFAULT_BUSINESS;
  if (business.vatPeriod === "annual") return null;
  if (business.vatPeriod === "monthly") return "months=1";
  return business.stagger === "custom" ? `start_month=${business.customStartMonth}` : `stagger=${business.stagger}`;
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
