"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useReviewBadge } from "./AppNav";
import ScanBadge from "./ScanBadge";
import { AccountMenu, ProfileSwitcher, useLinkedProfiles } from "./ProfileMenu";
import { activeRoute, isCurrent, routeOf, visibleGroups, type NavGroup, type NavItem } from "@/lib/nav";
import { useSelfEmployed } from "@/lib/itsa";
import { usePersonalOn } from "@/lib/personal";
import { useLandlordOn } from "@/lib/property";
import { currentFeatures, currentMeta } from "@/lib/profiles";

/**
 * The signed-in menu bar, laid out like Xero's (the owner's choice; docs/reviews/app-shell/REVIEW.md weighs it against
 * docs/research/DASHBOARD.md's sidebar): the logo and the profile switcher (current profile, its kind, every linked
 * profile) at the far left, then Home, Review (with its count) and Bank as plain links and Sales, Purchases, Reporting,
 * Tax and More (Accounting, Payroll, Contacts, Personal) as dropdowns, then Search, Ask, Help and the Review count, and at the far right
 * the signed-in person's name and Microsoft email with the account menu (sign out). Under 900 px the groups move
 * into a drawer opened by "Menu"; there is no sidebar for signed-in pages. Links come from lib/nav.ts: only pages in
 * this build (`routes`), only features this profile has.
 *
 * AppShell renders it whenever this device is signed in, even before MSAL has answered or when MSAL can no longer
 * read the sign-in: then the right-hand side says "Sign in again" instead of disappearing (it used to return null,
 * which left a signed-in page with the signed-out sidebar and no bar at all).
 *
 * Keyboard: each group is a disclosure button (WAI-ARIA APG "disclosure navigation"): Enter/Space/↓ open it, ↑/↓
 * move through its links, Escape closes it and returns to its button, Tab moves on; one group is open at a time.
 */
export default function TopBar({ routes }: { routes: string[] }) {
  const linked = useLinkedProfiles();
  const pathname = usePathname();
  const review = useReviewBadge(pathname);
  const meta = currentMeta();
  const features = currentFeatures();
  // Re-read on every render (useLinkedProfiles re-renders on a change); compared by value.
  const featureKey = JSON.stringify(features);
  const kind = meta?.exists ? meta.kind : null;
  const personal = usePersonalOn();
  const selfEmployed = useSelfEmployed() || Boolean(features?.includes("self_employment"));
  const landlord = useLandlordOn();
  const groups = useMemo(
    () =>
      visibleGroups(routes, { features: JSON.parse(featureKey) as string[] | null, kind, personal, selfEmployed, landlord }),
    [routes, featureKey, kind, personal, selfEmployed, landlord],
  );

  return (
    <header
      data-topnav=""
      className="sticky top-0 z-40 border-b border-border bg-white print:hidden"
    >
      <SideBar groups={groups} pathname={pathname} review={review} />
      <div className="flex min-h-14 items-center gap-1 px-2 sm:px-4 min-[1280px]:min-h-16 min-[1280px]:px-8">
        <MenuDrawer groups={groups} pathname={pathname} review={review} />
        <Link href="/" aria-label="Accnomos home" className="flex h-11 shrink-0 items-center gap-2 rounded-lg px-1.5 hover:bg-ground min-[1280px]:hidden">
          <LogoMark />
          <span className="hidden text-lg font-extrabold tracking-tight 2xl:inline">Accnomos</span>
        </Link>
        {linked && <ProfileSwitcher linked={linked} />}
        <nav aria-label="Main" className="ml-2 hidden min-w-0 flex-1 min-[900px]:block min-[1280px]:hidden">
          <GroupBar groups={groups} pathname={pathname} review={review} />
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <ScanBadge />
          <FindPage groups={groups} />
          <IconLink href="/ask" label="Ask" current={isCurrent(pathname, "/ask")}>
            <path d="M4 5.5h12v8H8.5L5 16.5v-3H4z" />
          </IconLink>
          <IconLink href="/help" label="Help" current={isCurrent(pathname, "/help")} narrowHidden>
            <circle cx="10" cy="10" r="7" />
            <path d="M8.2 8a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.6M10 13.6v.1" />
          </IconLink>
          <IconLink
            href="/review"
            label={review ? `Notifications: ${review} item${review === "1" ? "" : "s"} to review` : "Notifications: nothing to review"}
            current={false}
            badge={review}
            narrowHidden
          >
            <path d="M6 13.5V9a4 4 0 0 1 8 0v4.5l1.2 1.5H4.8zM8.5 16.5a1.6 1.6 0 0 0 3 0" />
          </IconLink>
          {linked ? <AccountMenu linked={linked} /> : linked === null ? <SignInAgain pathname={pathname} /> : null}
        </div>
      </div>
    </header>
  );
}

/** The app's mark (the same as the signed-out header's and the public site's). */
export function LogoMark() {
  return (
    <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6L10 2.5Z" stroke="#F4F3EE" strokeWidth="1.8" strokeLinejoin="round" />
        <path d="M7 10.2l2.1 2.1L13.2 8" stroke="#F4F3EE" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** This device looks signed in but MSAL has no account it can use: say so where the account menu would be. */
function SignInAgain({ pathname }: { pathname: string }) {
  return (
    <Link
      href={`/connect?next=${encodeURIComponent(pathname)}`}
      className="ml-1 flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-xl bg-teal px-3 text-sm font-bold text-white hover:bg-teal-dark"
    >
      Sign in again
    </Link>
  );
}

/**
 * Second-level links (inside a group) look clearly lower than the groups themselves (docs/research/DASHBOARD.md §9):
 * indented behind a rule, smaller type (14 px, not 15), normal weight (not semibold), under the group's small
 * uppercase label; the current page has a teal bar, a tint and semibold text, and aria-current.
 */
const subItem = (current: boolean, tall: boolean) =>
  `relative flex ${tall ? "min-h-11" : "min-h-10"} items-center gap-2 rounded-lg py-1.5 pl-3 pr-3 text-[14px] ${
    current
      ? "bg-teal-tint font-semibold text-teal-dark before:absolute before:inset-y-1.5 before:-left-[9px] before:w-[3px] before:rounded-full before:bg-teal"
      : "font-normal text-ink hover:bg-ground"
  }`;
const subList = "ml-3 flex flex-col gap-0.5 border-l border-border pl-2";
const sectionLabel = "px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-muted";

/** The sidebar's second-level links: on dark teal, smaller and lighter than the groups, indented behind a faint rule. */
const sideSubItem = (current: boolean) =>
  `relative flex min-h-10 items-center gap-2 rounded-lg py-1.5 pl-3 pr-2 text-[14px] ${
    current
      ? "bg-white/12 font-semibold text-white before:absolute before:inset-y-1.5 before:-left-[9px] before:w-[3px] before:rounded-full before:bg-brass"
      : "font-normal text-white/80 hover:bg-white/10 hover:text-white"
  }`;
const sideSubList = "ml-[22px] flex flex-col gap-0.5 border-l border-white/15 pl-2";
const sideSectionLabel = "px-3 text-[11px] font-bold uppercase tracking-[0.08em] text-white/60";

const iconButton = "relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink hover:bg-ground";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

function IconLink({
  href,
  label,
  current,
  badge,
  narrowHidden,
  children,
}: {
  href: string;
  label: string;
  current: boolean;
  badge?: string;
  narrowHidden?: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      aria-current={current ? "page" : undefined}
      className={`${iconButton} ${narrowHidden ? "max-[479px]:hidden" : ""}`}
    >
      <Icon>{children}</Icon>
      {badge ? (
        <span aria-hidden="true" className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber px-1 text-[10px] font-bold text-white">
          {badge}
        </span>
      ) : null}
    </Link>
  );
}

function itemLabel(item: NavItem, review: string | undefined): ReactNode {
  if (item.badge !== "review" || !review) return item.label;
  return (
    <>
      {item.label}{" "}
      <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-amber px-1.5 text-[12px] font-bold text-white">{review}</span>
      <span className="sr-only"> item{review === "1" ? "" : "s"} to review</span>
    </>
  );
}

/** A plain top-level link's text, with the Review count beside it (spoken as "N items to review"). */
function linkLabel(g: NavGroup, review: string | undefined): ReactNode {
  if (g.badge !== "review" || !review) return g.label;
  return (
    <>
      {g.label}
      <span aria-hidden="true" className="ml-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber px-1.5 text-[12px] font-bold text-white">
        {review}
      </span>
      <span className="sr-only">, {review} item{review === "1" ? "" : "s"} to review</span>
    </>
  );
}

/** The small heading above the first item of each section of More. */
function headed(items: NavItem[], i: number): string | undefined {
  const h = items[i].heading;
  return h && h !== items[i - 1]?.heading ? h : undefined;
}

/** aria-current only on the item whose page this is: the most specific match (lib/nav.ts activeRoute). */
function currentPage(active: string | null, item: NavItem): boolean {
  return !/[?#]/.test(item.href) && routeOf(item.href) === active;
}

/** The groups as disclosure dropdowns (900–1279 px), or, `vertical`, as the sidebar's disclosure groups (≥ 1280 px). */
function GroupBar({
  groups,
  pathname,
  review,
  vertical = false,
}: {
  groups: NavGroup[];
  pathname: string;
  review: string | undefined;
  vertical?: boolean;
}) {
  const active = activeRoute(pathname, groups);
  const [open, setOpen] = useState<string | null>(null);
  const bar = useRef<HTMLUListElement>(null);
  const base = useId();

  useEffect(() => {
    if (!open || vertical) return; // the sidebar's groups stay open until toggled or a new page opens
    const away = (e: MouseEvent) => !bar.current?.contains(e.target as Node) && setOpen(null);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open, vertical]);

  const [seen, setSeen] = useState(pathname); // a new page closes the open group
  if (seen !== pathname) {
    setSeen(pathname);
    setOpen(null);
  }

  const links = (id: string) => Array.from(document.getElementById(id)?.querySelectorAll<HTMLElement>("a") ?? []);
  const focusButton = (label: string) => document.getElementById(`${base}-${label}-button`)?.focus();

  function onButtonKey(e: KeyboardEvent<HTMLButtonElement>, label: string) {
    const id = `${base}-${label}`;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(label);
      requestAnimationFrame(() => links(id)[0]?.focus());
    } else if (e.key === "Escape" && open === label) {
      e.preventDefault();
      setOpen(null);
    }
  }

  function onListKey(e: KeyboardEvent<HTMLUListElement>, label: string) {
    const list = links(`${base}-${label}`);
    const i = list.indexOf(document.activeElement as HTMLElement);
    const go = (n: number) => {
      e.preventDefault();
      list[(n + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(null);
      focusButton(label);
    }
  }

  const top = vertical
    ? "flex h-11 w-full items-center gap-3 whitespace-nowrap rounded-lg px-3 text-left text-[15px] font-semibold"
    : "flex h-11 items-center gap-1 whitespace-nowrap rounded-lg px-2.5 text-[15px] font-semibold 2xl:px-3";
  const tone = (here: boolean) =>
    vertical
      ? here
        ? "bg-sidebar-active text-white"
        : "text-white/90 hover:bg-white/10 hover:text-white"
      : here
        ? "bg-teal-tint text-teal-dark"
        : "text-ink hover:bg-ground";

  return (
    <ul ref={bar} className={vertical ? "flex flex-col gap-0.5" : "flex flex-wrap items-center gap-0.5"}>
      {groups.map((g) => {
        if (g.href) {
          const here = routeOf(g.href) === active; // the most specific match, so Bank is not lit on Bank rules
          return (
            <li key={g.label}>
              <Link href={g.href} aria-current={here ? "page" : undefined} className={`${top} ${tone(here)}`}>
                {vertical && <NavIcon label={g.label} />}
                {linkLabel(g, review)}
              </Link>
            </li>
          );
        }
        const id = `${base}-${g.label}`;
        const isOpen = open === g.label;
        const here = g.items.some((i) => currentPage(active, i));
        const count = g.items.some((i) => i.badge === "review") ? review : undefined;
        return (
          <li
            key={g.label}
            className="relative"
            onBlur={(e) => {
              if (isOpen && !e.currentTarget.contains(e.relatedTarget as Node)) setOpen(null);
            }}
          >
            <button
              id={`${id}-button`}
              type="button"
              aria-expanded={isOpen}
              aria-controls={id}
              onClick={() => setOpen(isOpen ? null : g.label)}
              onKeyDown={(e) => onButtonKey(e, g.label)}
              className={`${top} ${tone(here)}`}
            >
              {vertical && <NavIcon label={g.label} />}
              {g.label}
              {count ? (
                <>
                  <span aria-hidden="true" className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber px-1.5 text-[12px] font-bold text-white">
                    {count}
                  </span>
                  <span className="sr-only">, {count} to review</span>
                </>
              ) : null}
              <svg
                aria-hidden="true"
                width="12"
                height="12"
                viewBox="0 0 12 12"
                className={`${vertical ? `ml-auto text-white/70 ${isOpen ? "rotate-180" : ""}` : "text-muted"}`}
              >
                <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <div
              hidden={!isOpen}
              className={
                vertical
                  ? "pb-1 pt-0.5"
                  : "absolute left-0 z-50 mt-1 max-h-[calc(100vh-5rem)] w-64 overflow-y-auto rounded-xl border border-border bg-white px-2 pb-2 pt-3 shadow-lg"
              }
            >
              {!vertical && (
                <p aria-hidden="true" className={`${sectionLabel} pb-1.5`}>
                  {g.label}
                </p>
              )}
              <ul id={id} data-submenu="" onKeyDown={(e) => onListKey(e, g.label)} className={vertical ? sideSubList : subList}>
                {g.items.map((item, i) => {
                  const page = currentPage(active, item);
                  const heading = headed(g.items, i);
                  return (
                    <li key={item.label}>
                      {heading ? (
                        <p aria-hidden="true" className={`${vertical ? sideSectionLabel : sectionLabel} pb-1 ${i ? "pt-2" : ""}`}>
                          {heading}
                        </p>
                      ) : null}
                      <Link
                        href={item.href}
                        aria-current={page ? "page" : undefined}
                        onClick={() => !vertical && setOpen(null)}
                        className={vertical ? sideSubItem(page) : subItem(page, false)}
                      >
                        {itemLabel(item, review)}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Items that sit under "Your plan" (Goals): their own section in the sidebar, under More in the bar and drawer. */
const PLAN = "Your plan";

/**
 * At 1280 px and wider: a 232 px dark-teal sidebar with the logo, the same groups as the menu bar (lib/nav.ts; each
 * group a disclosure that opens in place), Your plan, and Settings and Help at the bottom. It sits inside the banner
 * (the bar's own <header>) so the page keeps one banner and one "Main" navigation at any width; the bar's own links
 * hide at this width (AppShell pads the page by the sidebar's width).
 */
function SideBar({ groups, pathname, review }: { groups: NavGroup[]; pathname: string; review: string | undefined }) {
  const plan = groups.flatMap((g) => g.items.filter((i) => i.heading === PLAN));
  const rest = groups
    .map((g) => ({ ...g, items: g.items.filter((i) => i.heading !== PLAN) }))
    .filter((g) => g.href || g.items.length > 0);
  const active = activeRoute(pathname, groups);
  const bottom = "flex h-11 items-center gap-3 rounded-lg px-3 text-[15px] font-semibold";
  const tone = (here: boolean) => (here ? "bg-sidebar-active text-white" : "text-white/90 hover:bg-white/10 hover:text-white");
  return (
    <div
      data-sidebar=""
      className="on-dark fixed inset-y-0 left-0 z-40 hidden w-[232px] flex-col overflow-y-auto bg-sidebar px-4 pb-4 pt-5 text-white min-[1280px]:flex"
    >
      <Link href="/" aria-label="Accnomos home" className="flex h-11 shrink-0 items-center gap-2.5 rounded-lg px-2">
        <LogoMark />
        <span className="text-lg font-extrabold tracking-tight">Accnomos</span>
      </Link>
      <nav aria-label="Main" className="mt-6">
        <GroupBar groups={rest} pathname={pathname} review={review} vertical />
        {plan.length > 0 && (
          <>
            <p aria-hidden="true" className={`${sideSectionLabel} mt-5 pb-1.5`}>
              {PLAN}
            </p>
            <ul className="flex flex-col gap-0.5">
              {plan.map((item) => {
                const here = currentPage(active, item);
                return (
                  <li key={item.href}>
                    <Link href={item.href} aria-current={here ? "page" : undefined} className={`${bottom} ${tone(here)}`}>
                      <NavIcon label={item.label} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </nav>
      <div className="mt-auto flex flex-col gap-0.5 border-t border-white/15 pt-4">
        <Link href="/settings" className={`${bottom} ${tone(isCurrent(pathname, "/settings"))}`}>
          <NavIcon label="Settings" />
          Settings
        </Link>
        <Link href="/help" className={`${bottom} ${tone(isCurrent(pathname, "/help"))}`}>
          <NavIcon label="Help" />
          Help &amp; support
        </Link>
      </div>
    </div>
  );
}

const NAV_ICONS: Record<string, ReactNode> = {
  Home: <path d="M3.5 9.5 10 4l6.5 5.5M5.5 8v8h9V8" />,
  Review: (
    <>
      <rect x="3.5" y="3.5" width="13" height="13" rx="2" />
      <path d="m7 10 2.2 2.2L13.5 8" />
    </>
  ),
  Bank: <path d="M3 8h14L10 4zM5 8v7M8.5 8v7M11.5 8v7M15 8v7M3 16.5h14" />,
  Sales: <path d="M3.5 14.5 8 10l3 3 5.5-6.5M12.5 6.5h4v4" />,
  Purchases: <path d="M16.5 5.5 12 10l-3-3-5.5 6.5M7.5 13.5h-4v-4" />,
  Reporting: <path d="M4 16.5V9M8 16.5V5M12 16.5v-6M16 16.5V7.5" />,
  Tax: (
    <>
      <rect x="4" y="3" width="12" height="14" rx="1.5" />
      <path d="M7 7h6M7 10h6M7 13h3" />
    </>
  ),
  More: (
    <>
      <circle cx="5" cy="10" r="1" />
      <circle cx="10" cy="10" r="1" />
      <circle cx="15" cy="10" r="1" />
    </>
  ),
  Goals: (
    <>
      <circle cx="10" cy="10" r="6.5" />
      <circle cx="10" cy="10" r="3" />
      <circle cx="10" cy="10" r=".6" />
    </>
  ),
  Settings: (
    <>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 3v2M10 15v2M3 10h2M15 10h2M5 5l1.4 1.4M13.6 13.6 15 15M5 15l1.4-1.4M13.6 6.4 15 5" />
    </>
  ),
  Help: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M8.2 8a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.6M10 13.6v.1" />
    </>
  ),
};

/** A 20 px line icon for a sidebar row (none for an unknown label). */
function NavIcon({ label }: { label: string }) {
  const d = NAV_ICONS[label];
  return d ? <Icon>{d}</Icon> : <span aria-hidden="true" className="w-5" />;
}

/** A native modal <dialog> (page behind inert, Escape closes, focus back to the opener), as components/Explain.tsx. */
function useModal(open: boolean, setOpen: (o: boolean) => void, opener: React.RefObject<HTMLButtonElement | null>) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (!open || !d) return;
    const button = opener.current;
    d.showModal();
    const cancel = (e: Event) => {
      e.preventDefault();
      setOpen(false);
    };
    const closed = () => setOpen(false);
    d.addEventListener("cancel", cancel);
    d.addEventListener("close", closed);
    return () => {
      d.removeEventListener("cancel", cancel);
      d.removeEventListener("close", closed);
      d.close();
      button?.focus({ preventScroll: true });
    };
  }, [open, setOpen, opener]);
  return dialog;
}

/** Under 900 px: "Menu" opens a drawer with every group, its links listed under the group's heading. */
function MenuDrawer({ groups, pathname, review }: { groups: NavGroup[]; pathname: string; review: string | undefined }) {
  const active = activeRoute(pathname, groups);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const dialog = useModal(open, setOpen, opener);
  const id = useId();
  const [seen, setSeen] = useState(pathname); // a new page closes the drawer
  if (seen !== pathname) {
    setSeen(pathname);
    setOpen(false);
  }

  return (
    <>
      <button
        ref={opener}
        type="button"
        aria-label="Menu"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(true)}
        className={`${iconButton} min-[900px]:hidden`}
      >
        <Icon>
          <path d="M3.5 6h13M3.5 10h13M3.5 14h13" />
        </Icon>
      </button>
      {open && (
        <dialog
          ref={dialog}
          id={id}
          aria-label="Menu"
          onClick={(e) => e.target === dialog.current && setOpen(false)}
          className="fixed inset-y-0 left-0 m-0 h-full max-h-none w-[min(22rem,88vw)] max-w-none overflow-y-auto rounded-r-2xl border-r border-border bg-white p-0 text-ink backdrop:bg-ink/40"
        >
          <div className="p-4 pb-8">
            <div className="flex items-center justify-between gap-3">
              <p className="text-lg font-extrabold tracking-tight">Menu</p>
              <button type="button" onClick={() => setOpen(false)} className="min-h-11 rounded-xl px-3 text-sm font-bold text-teal-dark hover:bg-ground">
                Close
              </button>
            </div>
            <nav aria-label="Main" className="mt-2">
              {groups.map((g) => (
                <section key={g.label} aria-labelledby={`${id}-${g.label}`} className="mt-3">
                  {g.href ? (
                    <Link
                      id={`${id}-${g.label}`}
                      href={g.href}
                      aria-current={routeOf(g.href) === active ? "page" : undefined}
                      className="flex min-h-11 items-center rounded-xl px-3 text-[15px] font-extrabold text-ink hover:bg-ground"
                    >
                      {linkLabel(g, review)}
                    </Link>
                  ) : (
                    <>
                      <h2 id={`${id}-${g.label}`} className="px-3 pb-1 text-[15px] font-extrabold text-ink">
                        {g.label}
                      </h2>
                      <ul data-submenu="" className={subList}>
                        {g.items.map((item, i) => (
                          <li key={item.label}>
                            {headed(g.items, i) ? <p className={`${sectionLabel} pb-1 pt-2`}>{headed(g.items, i)}</p> : null}
                            <Link
                              href={item.href}
                              aria-current={currentPage(active, item) ? "page" : undefined}
                              onClick={() => setOpen(false)}
                              className={subItem(currentPage(active, item), true)}
                            >
                              {itemLabel(item, review)}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </section>
              ))}
            </nav>
          </div>
        </dialog>
      )}
    </>
  );
}

/** Search: find a page in the menu by name (there is no search across the books yet; Ask answers questions). */
function FindPage({ groups }: { groups: NavGroup[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const router = useRouter();
  const opener = useRef<HTMLButtonElement>(null);
  const dialog = useModal(open, setOpen, opener);
  const id = useId();
  const all = useMemo(
    () =>
      groups.flatMap((g) =>
        g.href ? [{ label: g.label, href: g.href, group: "" }] : g.items.map((i) => ({ label: i.label, href: i.href, group: i.heading ?? g.label })),
      ),
    [groups],
  );
  const hits = q.trim() ? all.filter((x) => `${x.group} ${x.label}`.toLowerCase().includes(q.trim().toLowerCase())) : all;

  return (
    <>
      <button
        ref={opener}
        type="button"
        aria-label="Search"
        title="Search"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          setQ("");
          setOpen(true);
        }}
        className={iconButton}
      >
        <Icon>
          <circle cx="9" cy="9" r="5" />
          <path d="m13 13 3.5 3.5" />
        </Icon>
      </button>
      {open && (
        <dialog
          ref={dialog}
          id={id}
          aria-labelledby={`${id}-title`}
          onClick={(e) => e.target === dialog.current && setOpen(false)}
          className="m-auto mt-16 w-[min(30rem,calc(100vw-2rem))] rounded-2xl border border-border bg-white p-0 text-ink backdrop:bg-ink/40"
        >
          <form
            className="p-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!hits[0]) return;
              setOpen(false);
              router.push(hits[0].href);
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <h2 id={`${id}-title`} className="text-lg font-extrabold tracking-tight">
                Find a page
              </h2>
              <button type="button" onClick={() => setOpen(false)} className="min-h-11 rounded-xl px-3 text-sm font-bold text-teal-dark hover:bg-ground">
                Close
              </button>
            </div>
            <label htmlFor={`${id}-q`} className="mt-2 block text-xs font-bold text-muted">
              Page name
            </label>
            <input
              id={`${id}-q`}
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]"
              placeholder="e.g. invoices"
            />
            <p role="status" className="sr-only">
              {hits.length} page{hits.length === 1 ? "" : "s"}
            </p>
            <ul className="mt-2 max-h-[50vh] overflow-y-auto">
              {hits.map((x) => (
                <li key={`${x.group}-${x.label}`}>
                  <Link href={x.href} onClick={() => setOpen(false)} className="flex min-h-11 items-center gap-2 rounded-xl px-3 text-[15px] font-semibold hover:bg-ground">
                    {x.label}
                    {x.group ? <span className="text-xs font-normal text-muted">{x.group}</span> : null}
                  </Link>
                </li>
              ))}
            </ul>
          </form>
        </dialog>
      )}
    </>
  );
}
