"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useReviewBadge } from "./AppNav";
import { AccountMenu, ProfileSwitcher, useLinkedProfiles } from "./ProfileMenu";
import { isCurrent, visibleGroups, type NavGroup, type NavItem } from "@/lib/nav";
import { useSelfEmployed } from "@/lib/itsa";
import { usePersonalOn } from "@/lib/personal";
import { useLandlordOn } from "@/lib/property";
import { currentFeatures, currentMeta } from "@/lib/profiles";

/**
 * The signed-in menu bar, laid out like Xero's: the profile switcher at the far left, the menu groups (Home, Sales,
 * Purchases, Reporting, Accounting, Tax, Payroll, Contacts, and Personal for personal books) as dropdowns, then
 * Search, Ask, Help and Notifications and the account menu at the right. Under 900 px the groups move into a
 * drawer opened by "Menu". It carries `data-topnav`, which hides the signed-out sidebar and phone header
 * (AppShell). Links come from lib/nav.ts: only pages in this build (`routes`), only features this profile has.
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
  if (!linked) return null;

  return (
    <header
      data-topnav=""
      className="sticky top-0 z-40 border-b border-border bg-white print:hidden"
    >
      <div className="flex min-h-14 items-center gap-1 px-2 sm:px-4">
        <MenuDrawer groups={groups} pathname={pathname} review={review} />
        <ProfileSwitcher linked={linked} />
        <nav aria-label="Main" className="ml-2 hidden min-w-0 flex-1 min-[900px]:block">
          <GroupBar groups={groups} pathname={pathname} review={review} />
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <FindPage groups={groups} />
          <IconLink href="/ask" label="Ask" current={isCurrent(pathname, "/ask")}>
            <path d="M4 5.5h12v8H8.5L5 16.5v-3H4z" />
          </IconLink>
          <IconLink href="/how-it-works" label="Help" current={isCurrent(pathname, "/how-it-works")} narrowHidden>
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
          <AccountMenu linked={linked} />
        </div>
      </div>
    </header>
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

/** aria-current only on the link whose page this is (not on "#section" links into it). */
function currentPage(pathname: string, item: NavItem): boolean {
  return !/[?#]/.test(item.href) && isCurrent(pathname, item.href);
}

/** The groups as disclosure dropdowns (≥ 900 px). */
function GroupBar({ groups, pathname, review }: { groups: NavGroup[]; pathname: string; review: string | undefined }) {
  const [open, setOpen] = useState<string | null>(null);
  const bar = useRef<HTMLUListElement>(null);
  const base = useId();

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !bar.current?.contains(e.target as Node) && setOpen(null);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

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

  const top = "flex h-11 items-center gap-1 whitespace-nowrap rounded-xl px-3 text-[15px] font-semibold";

  return (
    <ul ref={bar} className="flex flex-wrap items-center gap-0.5">
      {groups.map((g) => {
        if (g.href) {
          const here = isCurrent(pathname, g.href);
          return (
            <li key={g.label}>
              <Link href={g.href} aria-current={here ? "page" : undefined} className={`${top} ${here ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"}`}>
                {g.label}
              </Link>
            </li>
          );
        }
        const id = `${base}-${g.label}`;
        const isOpen = open === g.label;
        const here = g.items.some((i) => currentPage(pathname, i));
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
              className={`${top} ${here ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"}`}
            >
              {g.label}
              {count ? (
                <>
                  <span aria-hidden="true" className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber px-1.5 text-[12px] font-bold text-white">
                    {count}
                  </span>
                  <span className="sr-only">, {count} to review</span>
                </>
              ) : null}
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" className="text-muted">
                <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
            <div hidden={!isOpen} className="absolute left-0 z-50 mt-1 w-64 rounded-2xl border border-border bg-white px-2 pb-2 pt-3 shadow-lg">
              <p aria-hidden="true" className={`${sectionLabel} pb-1.5`}>
                {g.label}
              </p>
              <ul id={id} data-submenu="" onKeyDown={(e) => onListKey(e, g.label)} className={subList}>
                {g.items.map((item) => {
                  const page = currentPage(pathname, item);
                  return (
                    <li key={item.label}>
                      <Link
                        href={item.href}
                        aria-current={page ? "page" : undefined}
                        onClick={() => setOpen(null)}
                        className={subItem(page, false)}
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
                      aria-current={isCurrent(pathname, g.href) ? "page" : undefined}
                      className="flex min-h-11 items-center rounded-xl px-3 text-[15px] font-extrabold text-ink hover:bg-ground"
                    >
                      {g.label}
                    </Link>
                  ) : (
                    <>
                      <h2 id={`${id}-${g.label}`} className="px-3 pb-1 text-[15px] font-extrabold text-ink">
                        {g.label}
                      </h2>
                      <ul data-submenu="" className={subList}>
                        {g.items.map((item) => (
                          <li key={item.label}>
                            <Link
                              href={item.href}
                              aria-current={currentPage(pathname, item) ? "page" : undefined}
                              onClick={() => setOpen(false)}
                              className={subItem(currentPage(pathname, item), true)}
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
        g.href ? [{ label: g.label, href: g.href, group: "" }] : g.items.map((i) => ({ label: i.label, href: i.href, group: g.label })),
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
