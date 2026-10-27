"use client";

/**
 * The user's business details (onboarding step 3). Lives only on this device
 * (localStorage) — the static export has no server to store it on.
 */

export type VatPeriod = "quarterly" | "monthly" | "annual";

export type PeriodEnd = "Mar/Jun/Sep/Dec" | "Jan/Apr/Jul/Oct" | "Feb/May/Aug/Nov";

export interface Business {
  name: string;
  vatNumber: string;
  vatPeriod: VatPeriod;
  periodEnd: PeriodEnd;
  flatRate: boolean;
  email: string;
}

const KEY = "accnomos.business";

export const DEFAULT_BUSINESS: Business = {
  name: "",
  vatNumber: "",
  vatPeriod: "quarterly",
  periodEnd: "Mar/Jun/Sep/Dec",
  flatRate: false,
  email: "",
};

export function loadBusiness(): Business | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Business>;
    return { ...DEFAULT_BUSINESS, ...parsed, flatRate: parsed.flatRate === true };
  } catch {
    return null;
  }
}

export function saveBusiness(business: Business): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(business));
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
