/**
 * The signed-in menu bar (components/TopBar.tsx), grouped like Xero's: Home, Review (with its count) and Bank as plain
 * links so the two things an owner acts on most are one click away, then Sales, Purchases, Reporting, Tax and More.
 * More holds the rest under small headings: Your plan (Goals), Accounting, Payroll, Contacts and, when Settings ›
 * Show personal finances is on, Personal. Personal books have a menu of their own (HOUSEHOLD_GROUPS). At 1280 px and wider the same groups sit in a dark-teal sidebar (TopBar.tsx SideBar), Your plan as its own
 * section there.
 *
 * Other work is building some of these pages. A link shows only when its page is in this build (`routes`, read
 * from src/app at build time by lib/routes.server.ts), so nothing in the menu 404s, and only when the profile's kind
 * has the feature (services/runtime/app/profile.py: personal books have no VAT, invoices or payroll; VAT pages need
 * a VAT-registered business; self-employment is for sole traders).
 *
 * Every item opens its own page with its own heading (e2e/menu-pages.spec.ts): no two labels share a page or an
 * anchor. The same page may appear in two groups only under the same label (Customers under Sales and Contacts).
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
  /** A small heading above this item in a group (More), shown when it differs from the item before. */
  heading?: string;
  /** Only while this device switch is on: Settings › I am self-employed (lib/itsa.ts) or I let property (lib/property.ts). */
  deviceSwitch?: "selfEmployed" | "landlord";
}

export interface NavGroup {
  label: string;
  /** A group with a single destination is a plain link (Home). */
  href?: string;
  /** Shows the Review count beside a plain link. */
  badge?: "review";
  feature?: string;
  kinds?: RtProfileKind[];
  items: NavItem[];
}

const BUSINESS: RtProfileKind[] = ["company", "sole_trader"];

export const NAV_GROUPS: NavGroup[] = [
  { label: "Home", href: "/", items: [] },
  { label: "Review", href: "/review", badge: "review", items: [] },
  { label: "Bank", href: "/bank", items: [] },
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
      { label: "Customers", href: "/contacts/customers" },
      { label: "Sales settings", href: "/settings/sales" },
    ],
  },
  {
    label: "Purchases",
    items: [
      { label: "Purchases overview", href: "/purchases" },
      { label: "Bills (Review)", href: "/review", badge: "review" },
      { label: "Purchase orders", href: "/purchases/orders", kinds: BUSINESS },
      { label: "Suppliers", href: "/contacts/suppliers" },
    ],
  },
  {
    label: "Reporting",
    items: [
      { label: "All reports", href: "/reports" },
      { label: "Reports & exports", href: "/reports/exports" },
      { label: "VAT returns", href: "/vat", feature: "vat" },
      { label: "Profit and loss", href: "/reports/profit-and-loss", kinds: BUSINESS },
      { label: "Balance sheet", href: "/reports/balance-sheet", kinds: BUSINESS },
      { label: "Aged receivables and payables", href: "/reports/aged", kinds: BUSINESS },
      { label: "Short-term cash flow", href: "/reports/cashflow" },
      { label: "Budgets", href: "/reports/budgets" },
      { label: "Spending", href: "/spending" },
    ],
  },
  {
    label: "Tax",
    items: [
      { label: "VAT returns", href: "/vat", feature: "vat" },
      // Sole traders (feature self_employment), or anyone who ticked Settings › I am self-employed (TopBar `who`).
      { label: "Self-employment (MTD Income Tax)", href: "/self-employment", deviceSwitch: "selfEmployed" },
      { label: "Property (landlords)", href: "/property", deviceSwitch: "landlord" },
      { label: "CIS (construction)", href: "/cis", kinds: BUSINESS },
      { label: "Tax settings", href: "/settings/tax", feature: "vat" },
    ],
  },
  {
    label: "More",
    items: [
      // Your plan: shown as its own small section in the wide-screen sidebar (TopBar.tsx SideBar), under More elsewhere.
      { heading: "Your plan", label: "Goals & progress", href: "/goals" },
      { heading: "Your plan", label: "Calendar", href: "/calendar" },
      { heading: "Your plan", label: "Notes", href: "/notes" },
      { heading: "Accounting", label: "Bank rules", href: "/bank/rules" },
      { heading: "Accounting", label: "Reconcile", href: "/bank/reconcile" },
      { heading: "Accounting", label: "Documents", href: "/files" },
      { heading: "Accounting", label: "Chart of accounts", href: "/accounting/chart" },
      { heading: "Accounting", label: "Fixed assets", href: "/accounting/assets", kinds: BUSINESS },
      { heading: "Accounting", label: "Manual journals", href: "/accounting/journals" },
      { heading: "Accounting", label: "Find and recode", href: "/accounting/recode" },
      { heading: "Accounting", label: "Tracking", href: "/accounting/tracking" },
      { heading: "Accounting", label: "Vehicles and mileage", href: "/vehicles" },
      { heading: "Accounting", label: "Audit trail", href: "/audit" },
      { heading: "Payroll", label: "Employees", href: "/settings/employees", feature: "payroll" },
      { heading: "Payroll", label: "Pay runs", href: "/payroll", feature: "payroll" },
      { heading: "Payroll", label: "RTI files", href: "/payroll/rti", feature: "payroll" },
      { heading: "Payroll", label: "Pensions", href: "/payroll/pensions", feature: "payroll" },
      { heading: "Contacts", label: "All contacts", href: "/contacts" },
      { heading: "Contacts", label: "Customers", href: "/contacts/customers", feature: "invoices" },
      { heading: "Contacts", label: "Suppliers", href: "/contacts/suppliers" },
      { heading: "Personal", label: "Personal overview", href: "/personal", kinds: ["personal"] },
      { heading: "Personal", label: "Spending", href: "/spending", kinds: ["personal"] },
      { heading: "Personal", label: "Shopping", href: "/shopping", kinds: ["personal"] },
    ],
  },
];

/**
 * Personal books (profile kind "personal") get their own menu, as each business kind gets its own features: a
 * household has no sales, VAT, payroll or ledger housekeeping, so instead of the business menu with gaps it gets the
 * pages a household uses. Budget is the household overview (/personal: categories, monthly budgets, bills and the
 * month's summary). Vehicles and mileage stays out: personal mileage is not claimable, and a self-employed person's
 * business mileage belongs with Self-employment, which shows here (with Property) only while its device switch is on.
 */
export const HOUSEHOLD_GROUPS: NavGroup[] = [
  { label: "Home", href: "/", items: [] },
  { label: "Review", href: "/review", badge: "review", items: [] },
  { label: "Bank", href: "/bank", items: [] },
  { label: "Budget", href: "/personal", items: [] },
  {
    label: "Spending",
    items: [
      { label: "Spending overview", href: "/spending" },
      { label: "Cheaper options", href: "/prices" },
      { label: "Shopping list", href: "/shopping" },
    ],
  },
  { label: "Goals", href: "/goals", items: [] },
  {
    label: "More",
    items: [
      { heading: "Your plan", label: "Calendar", href: "/calendar" },
      { heading: "Money", label: "Bank rules", href: "/bank/rules" },
      { heading: "Money", label: "Short-term cash flow", href: "/reports/cashflow" },
      { heading: "Money", label: "Reports & exports", href: "/reports/exports" },
      { heading: "Records", label: "Notes", href: "/notes" },
      { heading: "Records", label: "Documents", href: "/files" },
      { heading: "Records", label: "Audit trail", href: "/audit" },
      { heading: "Records", label: "All contacts", href: "/contacts" },
      { heading: "Tax", label: "Self-employment (MTD Income Tax)", href: "/self-employment", deviceSwitch: "selfEmployed" },
      { heading: "Tax", label: "Property (landlords)", href: "/property", deviceSwitch: "landlord" },
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
  /** Settings › I am self-employed, and › I let property, on this device. */
  selfEmployed?: boolean;
  landlord?: boolean;
}

function allowed(x: { feature?: string; kinds?: RtProfileKind[]; deviceSwitch?: NavItem["deviceSwitch"] }, who: Who): boolean {
  if (x.deviceSwitch && !who[x.deviceSwitch]) return false;
  if (x.feature && who.features && !who.features.includes(x.feature)) return false;
  if (who.personal && x.kinds?.includes("personal")) return true;
  if (x.kinds && !(who.kind ? x.kinds.includes(who.kind) : !x.kinds.every((k) => k === "personal"))) return false;
  return true;
}

/** The groups and items to show: built pages only, allowed for this profile; empty groups dropped. */
export function visibleGroups(routes: readonly string[], who: Who): NavGroup[] {
  const built = new Set(routes);
  return (who.kind === "personal" ? HOUSEHOLD_GROUPS : NAV_GROUPS)
    .filter((g) => allowed(g, who))
    .map((g) => ({ ...g, items: g.items.filter((i) => built.has(routeOf(i.href)) && allowed(i, who)) }))
    .filter((g) => (g.href ? built.has(routeOf(g.href)) : g.items.length > 0));
}

/** Whether `pathname` is (inside) `href`'s page. */
export function isCurrent(pathname: string, href: string): boolean {
  const route = routeOf(href);
  if (route === "/") return pathname === "/";
  return pathname === route || pathname.startsWith(`${route}/`);
}

/**
 * The menu's current page: the most specific route among every item that `pathname` is (inside), so on /bank/rules
 * "Bank rules" is current and "Bank accounts" (/bank) is not. null when no item matches.
 */
export function activeRoute(pathname: string, groups: readonly NavGroup[]): string | null {
  let best: string | null = null;
  for (const href of groups.flatMap((g) => (g.href ? [g.href] : g.items.map((i) => i.href)))) {
    const route = routeOf(href);
    if (isCurrent(pathname, href) && (best === null || route.length > best.length)) best = route;
  }
  return best;
}
