"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Modal, { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { useAccount } from "@/components/jobs/useAccount";
import PageHeader from "@/components/PageHeader";
import { adminApi } from "@/lib/billing-api";

export const card = "rounded-2xl border border-border bg-white p-4";
export const h2 = "text-[17px] font-extrabold text-ink";
export const th = "px-3 py-2 text-left text-xs font-bold uppercase tracking-wide text-muted";
export const td = "px-3 py-2 align-top text-sm";
export const input = "h-10 rounded-xl border border-border bg-white px-3 text-sm text-ink";

const TABS: { href: string; label: string }[] = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/codes", label: "Promo codes" },
  { href: "/admin/plans", label: "Plans" },
  { href: "/admin/analytics", label: "Analytics" },
  { href: "/admin/bugs", label: "Bug reports" },
  { href: "/admin/audit", label: "Audit log" },
];

/**
 * Every /admin page: checks GET /admin/metrics (the runtime decides who is an administrator, from ADMIN_EMAILS) and
 * only then shows its content. Nothing links here for anyone else. Desktop first; the tabs and tables scroll sideways on a phone.
 */
export default function AdminFrame({ title, description, children }: { title: string; description: string; children: (a: AccountInfo) => ReactNode }) {
  const account = useAccount();
  const path = usePathname() ?? "/admin";
  const [state, setState] = useState<"checking" | "ok" | "denied">("checking");
  useEffect(() => {
    if (!account) return;
    let live = true;
    adminApi.metrics(account).then(
      () => live && setState("ok"),
      () => live && setState("denied"),
    );
    return () => {
      live = false;
    };
  }, [account]);

  if (account === null || state === "denied") {
    return (
      <div className={card} role="alert">
        <h1 className="text-2xl font-extrabold">Not available</h1>
        <p className="mt-1 text-sm text-muted">This area is for Accnomos administrators.</p>
      </div>
    );
  }
  return (
    <div data-admin="">
      <PageHeader title={title} description={description} />
      <nav aria-label="Admin" className="mt-4 overflow-x-auto">
        <ul className="flex gap-1 whitespace-nowrap border-b border-border pb-2">
          {TABS.map((t) => {
            const here = t.href === "/admin" ? path === "/admin" : path.startsWith(t.href) || (t.href === "/admin/users" && path.startsWith("/admin/user"));
            return (
              <li key={t.href}>
                <Link href={t.href} aria-current={here ? "page" : undefined} className={`inline-flex h-10 items-center rounded-xl px-3 text-[15px] font-bold ${here ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"}`}>
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="mt-4 space-y-4">{state === "ok" && account ? children(account) : <p className="text-sm text-muted">Checking access…</p>}</div>
    </div>
  );
}

/** A confirmation step before any write: says what will happen, runs it only on Confirm. */
export function ConfirmDialog({ title, body, confirmLabel = "Confirm", onConfirm, onCancel }: { title: string; body: ReactNode; confirmLabel?: string; onConfirm: () => Promise<void>; onCancel: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal id="admin-confirm-title" title={title} onClose={onCancel}>
      <div className="mt-3 text-[15px] leading-7 text-ink">{body}</div>
      <p className="mt-2 text-xs text-muted">This is written to the audit log.</p>
      {error && <p role="alert" className="mt-2 text-sm font-bold text-red-700">{error}</p>}
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className={primaryButton}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await onConfirm();
            } catch (e) {
              setError((e as Error).message);
              setBusy(false);
            }
          }}
        >
          {busy ? "Working…" : confirmLabel}
        </button>
        <button type="button" className={secondaryButton} onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </Modal>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className={card} data-stat={label}>
      <p className="text-xs font-bold uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-extrabold text-ink">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** A small SVG chart of one series: bars or a line. Labelled for screen readers by `label`. */
export function MiniChart({ data, label, kind = "bars" }: { data: { day: string; count: number }[]; label: string; kind?: "bars" | "line" }) {
  const w = 600;
  const hgt = 140;
  const max = Math.max(1, ...data.map((d) => d.count));
  const step = data.length > 1 ? w / (data.length - 1) : w;
  const bw = w / Math.max(1, data.length);
  return (
    <figure className="m-0">
      <svg role="img" aria-label={label} viewBox={`0 0 ${w} ${hgt + 18}`} className="h-44 w-full">
        <line x1="0" y1={hgt} x2={w} y2={hgt} stroke="currentColor" className="text-border" />
        {kind === "bars" ? (
          data.map((d, i) => {
            const bh = (d.count / max) * (hgt - 8);
            return <rect key={d.day} x={i * bw + 1} y={hgt - bh} width={Math.max(1, bw - 2)} height={bh} rx="2" className="fill-teal"><title>{`${d.day}: ${d.count}`}</title></rect>;
          })
        ) : (
          <polyline fill="none" strokeWidth="2.5" className="stroke-teal" points={data.map((d, i) => `${i * step},${hgt - (d.count / max) * (hgt - 8)}`).join(" ")} />
        )}
        <text x="0" y={hgt + 14} fontSize="11" className="fill-muted">{data[0]?.day ?? ""}</text>
        <text x={w} y={hgt + 14} fontSize="11" textAnchor="end" className="fill-muted">{data[data.length - 1]?.day ?? ""}</text>
        <text x={w} y="10" fontSize="11" textAnchor="end" className="fill-muted">max {max}</text>
      </svg>
      <figcaption className="sr-only">{label}: {data.map((d) => `${d.day} ${d.count}`).join(", ")}</figcaption>
    </figure>
  );
}

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    load().then(
      (d) => live && (setData(d), setError(null)),
      (e) => live && setError((e as Error).message),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

export const ErrorLine = ({ error }: { error: string | null }) => (error ? <p role="alert" className="text-sm font-bold text-red-700">{error}</p> : null);
