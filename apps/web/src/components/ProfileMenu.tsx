"use client";

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import AiSidebarLabel from "./AiSidebarLabel";
import { msalConfigured } from "@/lib/msal";
import {
  KIND_LABEL,
  linkedAccounts,
  PROFILE_EVENT,
  profileMeta,
  reconcile,
  rememberProfile,
  signOutOf,
  startAdding,
  switchTo,
  type ProfileMeta,
} from "@/lib/profiles";
import { runtime } from "@/lib/runtime";

const RELOADED = "accnomos.profiles.reloaded"; // sessionStorage: reconcile() reloads at most once per page

export interface Linked {
  active: AccountInfo;
  all: AccountInfo[];
}

/**
 * The linked sign-ins (lib/profiles.ts), with this browser's per-profile settings made the active profile's first.
 * null while checking or when signed out. Re-renders when a profile's details arrive or change.
 */
export function useLinkedProfiles(): Linked | null {
  const [linked, setLinked] = useState<Linked | null>(null);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!msalConfigured()) return;
    let stale = false;
    (async () => {
      try {
        const found = await linkedAccounts();
        if (stale || !found.active) return;
        if (reconcile(found.active.homeAccountId)) {
          let again = false;
          try {
            again = window.sessionStorage.getItem(RELOADED) === "1";
            window.sessionStorage.setItem(RELOADED, "1");
          } catch {
            again = true;
          }
          if (!again) return window.location.reload(); // this page read the other profile's settings
        }
        try {
          window.sessionStorage.removeItem(RELOADED);
        } catch {
          /* fine */
        }
        const active = found.active;
        setLinked({ active, all: found.all });
        const p = await runtime.profile(active);
        if (!stale) rememberProfile(active.homeAccountId, p);
      } catch {
        /* the runtime is down: the menus show what they know */
      }
    })();
    const onChange = () => setTick((t) => t + 1);
    window.addEventListener(PROFILE_EVENT, onChange);
    return () => {
      stale = true;
      window.removeEventListener(PROFILE_EVENT, onChange);
    };
  }, []);
  return linked;
}

export function profileLabel(account: AccountInfo, meta: ProfileMeta | undefined): { name: string; kind: string } {
  return {
    name: meta?.exists ? meta.name : account.name || account.username,
    kind: meta?.exists ? KIND_LABEL[meta.kind] : "Profile not set up",
  };
}

export const menuItemClass =
  "flex w-full min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-left text-[15px] font-semibold text-ink hover:bg-ground focus:bg-ground";

/**
 * A menu button (WAI-ARIA APG): Enter, Space or ↓ opens it on the first item (↑ on the last), ↑/↓/Home/End move,
 * Escape closes it and returns focus to the button, Tab or a click elsewhere closes it.
 */
export function MenuButton({
  label,
  menuLabel,
  className,
  align = "left",
  children,
  items,
}: {
  label?: string;
  menuLabel: string;
  className: string;
  align?: "left" | "right";
  children: ReactNode;
  /** The menu's items; choosing any of them closes the menu. */
  items: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();

  const all = useCallback(() => Array.from(menu.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? []), []);
  const close = useCallback((focusButton: boolean) => {
    setOpen(false);
    if (focusButton) button.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open, close]);

  function show(focus: "first" | "last") {
    setOpen(true);
    requestAnimationFrame(() => {
      const list = all();
      (focus === "first" ? list[0] : list[list.length - 1])?.focus();
    });
  }

  function onButtonKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      show("first");
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      show("last");
    }
  }

  function onMenuKey(e: KeyboardEvent<HTMLDivElement>) {
    const list = all();
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
      close(true);
    } else if (e.key === "Tab") close(false);
  }

  return (
    <div className="relative min-w-0">
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => (open ? close(false) : show("first"))}
        onKeyDown={onButtonKey}
        className={className}
      >
        {children}
      </button>
      {open && (
        <div
          ref={menu}
          id={id}
          role="menu"
          aria-label={menuLabel}
          onKeyDown={onMenuKey}
          onClick={(e) => (e.target as HTMLElement).closest('[role^="menuitem"]') && setOpen(false)}
          className={`absolute ${align === "right" ? "right-0" : "left-0"} z-50 mt-1 w-[min(20rem,calc(100vw-2rem))] rounded-2xl border border-border bg-white p-2 shadow-lg`}
        >
          {items}
        </div>
      )}
    </div>
  );
}

function Chevron() {
  return (
    <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" className="shrink-0 text-muted">
      <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Far left of the menu bar: the current profile (one Microsoft account's books) with a chevron. The menu lists every
 * linked profile to switch in one click, then "Add another account / business" and Settings.
 */
export function ProfileSwitcher({ linked }: { linked: Linked }) {
  const { active, all } = linked;
  const router = useRouter();
  const current = profileLabel(active, profileMeta(active.homeAccountId));
  return (
    <MenuButton
      menuLabel="Profiles"
      className="flex min-h-11 min-w-0 max-w-[11rem] items-center gap-2 rounded-xl px-2 py-1 text-left hover:bg-ground sm:max-w-[16rem]"
      items={
        <>
          <p className="px-3 pb-1 pt-1 text-[13px] font-bold text-muted" aria-hidden="true">
            Your profiles
          </p>
          {all.map((a) => {
            const l = profileLabel(a, profileMeta(a.homeAccountId));
            const isActive = a.homeAccountId === active.homeAccountId;
            return (
              <button
                key={a.homeAccountId}
                type="button"
                role="menuitemradio"
                aria-checked={isActive}
                tabIndex={-1}
                className={menuItemClass}
                onClick={() => !isActive && switchTo(a)}
              >
                <span
                  aria-hidden="true"
                  className={`h-2.5 w-2.5 shrink-0 rounded-full ${isActive ? "bg-teal" : "border border-border"}`}
                />
                <span className="min-w-0">
                  <span className="block truncate">{l.name}</span>
                  <span className="block truncate text-xs font-normal text-muted">
                    {l.kind}, {a.username}
                  </span>
                </span>
              </button>
            );
          })}
          <div role="separator" className="my-1 border-t border-border" />
          <button type="button" role="menuitem" tabIndex={-1} className={menuItemClass} onClick={() => {
              startAdding(active.homeAccountId);
              router.push("/connect?add=1");
            }}>
            Add another account / business
          </button>
          <Link href="/settings" role="menuitem" tabIndex={-1} className={menuItemClass}>
            Settings
          </Link>
        </>
      }
    >
      <span className="min-w-0">
        <span className="block truncate text-sm font-extrabold text-ink">
          <span className="sr-only">Profile: </span>
          {current.name}
        </span>
        <span className="block truncate text-xs text-muted">{current.kind}</span>
      </span>
      <Chevron />
    </MenuButton>
  );
}

function initials(account: AccountInfo): string {
  const words = (account.name || account.username).replace(/\(.*?\)/g, "").split(/[\s@._-]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Far right of the menu bar: the signed-in account (email, and the AI it reads with, which the signed-out sidebar
 *  shows) with Profile details and "Sign out of this one". */
export function AccountMenu({ linked }: { linked: Linked }) {
  const { active } = linked;
  return (
    <MenuButton
      menuLabel="Account"
      align="right"
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full hover:bg-ground"
      items={
        <>
          <div className="px-3 py-2">
            <p className="truncate text-[15px] font-bold text-ink">{active.name || active.username}</p>
            <p className="truncate text-sm text-muted">{active.username}</p>
            <div className="mt-2">
              <AiSidebarLabel />
            </div>
          </div>
          <div role="separator" className="my-1 border-t border-border" />
          <Link href="/settings#profile" role="menuitem" tabIndex={-1} className={menuItemClass}>
            Profile details
          </Link>
          <button type="button" role="menuitem" tabIndex={-1} className={menuItemClass} onClick={() => signOutOf(active)}>
            Sign out of this one
          </button>
        </>
      }
    >
      <span aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-full bg-teal text-sm font-bold text-white">
        {initials(active)}
      </span>
      {/* The name is this text, not an aria-label, so it never mismatches the visible initials (axe). */}
      <span className="sr-only">Account: {active.username}</span>
    </MenuButton>
  );
}
