/**
 * The signed-in menu bar (components/TopBar.tsx), grouped like Xero's: Home, Sales, Purchases, Reporting,
 * Accounting, Tax, Payroll, Contacts and, for personal books only, Personal.
 *
 * Other work is building some of these pages. A link shows only when its page is in this build (`routes`, read
 * from src/app at build time by lib/routes.server.ts), so nothing in the menu 404s, and only when the profile's kind
 * has the feature (services/runtime/app/profile.py: personal books have no VAT, invoices or payroll; VAT pages need
 * a VAT-registered business; self-employment is for sole traders).
 */

import type { RtProfileKind } from "./runtime";

export interface NavItem {
  label: string;
  href: string;
  /** A feature from GET /profile that must be on. */
  feature?: string;
  /** Only for these kinds of books. */
  kinds?: RtProfileKind[];
  /** Shows the Review count. */
  badge?: "review";
}

export interface NavGroup {
  label: string;
  /** A group with a single destination is a plain link (Home). */
  href?: string;
  feature?: string;
  kinds?: RtProfileKind[];
  items: NavItem[];
}

const BUSINESS: RtProfileKind[] = ["company", "sole_trader"];

export const NAV_GROUPS: NavGroup[] = [
  { label: "Home", href: "/", items: [] },
  {
    label: "Sales",
    feature: "invoices",
    items: [
      { label: "Sales overview", href: "/sales" },
      { label: "Invoices", href: "/invoices" },
      { label: "Quotes", href: "/sales/quotes" },
      { label: "Products and services", href: "/sales/items" },
      { label: "Repeating", href: "/sales/repeating" },
      { label: "Jobs", href: "/jobs" },
      { label: "Customers", href: "/contacts" },
      { label: "Sales settings", href: "/settings#settings-invoice-profile" },
    ],
  },
  {
    label: "Purchases",
    items: [
      { label: "Purchases overview", href: "/purchases" },
      { label: "Bills (Review)", href: "/review", badge: "review" },
      { label: "Purchase orders", href: "/purchases/orders", kinds: BUSINESS },
      { label: "Suppliers", href: "/contacts" },
    ],
  },
  {
    label: "Reporting",
    items: [
      { label: "All reports", href: "/reports" },
      { label: "VAT return", href: "/vat", feature: "vat" },
      { label: "Profit and loss", href: "/reports#pl-heading", kinds: BUSINESS },
      { label: "Balance sheet", href: "/reports/balance-sheet", kinds: BUSINESS },
      { label: "Aged receivables and payables", href: "/reports#aged-heading", kinds: BUSINESS },
      { label: "Short-term cash flow", href: "/reports/cashflow" },
      { label: "Budgets", href: "/reports/budgets" },
      { label: "Spending summary", href: "/spending" },
    ],
  },
  {
    label: "Accounting",
    items: [
      { label: "Bank accounts", href: "/bank" },
      { label: "Bank rules", href: "/bank#bank-rules" },
      { label: "Reconcile", href: "/bank#bank-action-heading" },
      { label: "Documents", href: "/files" },
      { label: "Chart of accounts", href: "/accounting/chart" },
      { label: "Fixed assets", href: "/accounting/assets", kinds: BUSINESS },
      { label: "Manual journals", href: "/accounting/journals" },
      { label: "Find and recode", href: "/accounting/recode" },
      { label: "Tracking", href: "/accounting/tracking" },
      { label: "Vehicles and mileage", href: "/vehicles" },
      { label: "Audit trail", href: "/audit" },
    ],
  },
  {
    label: "Tax",
    items: [
      { label: "VAT returns", href: "/vat", feature: "vat" },
      { label: "Self-employment (MTD Income Tax)", href: "/self-employment", feature: "self_employment" },
      { label: "Tax settings", href: "/settings#settings-vat-periods", feature: "vat" },
    ],
  },
  {
    label: "Payroll",
    feature: "payroll",
    items: [
      { label: "Employees", href: "/settings#settings-staff" },
      { label: "Pay runs", href: "/payroll" },
      { label: "RTI files", href: "/payroll/rti" },
      { label: "Pensions", href: "/payroll/pensions" },
    ],
  },
  {
    label: "Contacts",
    items: [
      { label: "All contacts", href: "/contacts" },
      { label: "Customers", href: "/contacts?show=customers", feature: "invoices" },
      { label: "Suppliers", href: "/contacts?show=suppliers" },
    ],
  },
  {
    label: "Personal",
    kinds: ["personal"],
    items: [
      { label: "Personal overview", href: "/personal" },
      { label: "Spending", href: "/spending" },
      { label: "Shopping", href: "/shopping" },
    ],
  },
];

/** "/reports#pl-heading" -> "/reports"; "/" stays "/". */
export function routeOf(href: string): string {
  const path = href.split(/[?#]/, 1)[0] || "/";
  return path.length > 1 ? path.replace(/\/$/, "") : path;
}

export interface Who {
  /** null: not known yet (show everything the build has). */
  features: string[] | null;
  kind: RtProfileKind | null;
  /** Settings › Show personal finances is on (this device): the Personal group shows for any kind. */
  personal?: boolean;
  /** Settings › "I am self-employed" is on (lib/itsa.ts): shows Self-employment whatever the profile says. */
  selfEmployed?: boolean;
}

function allowed(x: { feature?: string; kinds?: RtProfileKind[] }, who: Who): boolean {
  if (x.feature === "self_employment") {
    // Off by default (Settings › "I am self-employed"); a known profile with the feature also shows it.
    if (!who.selfEmployed && !who.features?.includes(x.feature)) return false;
  } else if (x.feature && who.features && !who.features.includes(x.feature)) return false;
  if (who.personal && x.kinds?.includes("personal")) return true;
  if (x.kinds && !(who.kind ? x.kinds.includes(who.kind) : !x.kinds.every((k) => k === "personal"))) return false;
  return true;
}

/** The groups and items to show: built pages only, allowed for this profile; empty groups dropped. */
export function visibleGroups(routes: readonly string[], who: Who): NavGroup[] {
  const built = new Set(routes);
  return NAV_GROUPS.filter((g) => allowed(g, who))
    .map((g) => ({ ...g, items: g.items.filter((i) => built.has(routeOf(i.href)) && allowed(i, who)) }))
    .filter((g) => (g.href ? built.has(routeOf(g.href)) : g.items.length > 0));
}

/** Whether `pathname` is (inside) `href`'s page. */
export function isCurrent(pathname: string, href: string): boolean {
  const route = routeOf(href);
  if (route === "/") return pathname === "/";
  return pathname === route || pathname.startsWith(`${route}/`);
}
