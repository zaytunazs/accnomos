import type { HTMLAttributes, ReactNode } from "react";

/**
 * One status badge for the whole app (Goals, Invoices, Bank, Review): the same padding, type and pill corner
 * everywhere, so only the tone and the words differ. The words always carry the meaning; the tone repeats it.
 *
 *   success   paid, matched, done, on track — pale green
 *   neutral   draft, void, ignored, a transfer, a count — quiet warm grey
 *   warning   overdue, at risk, to confirm, a penny out — amber
 *   negative  off track, over the limit, failed — red
 *   brand     an open state that is neither good nor bad (awaiting payment, exact match, the suggested action) — the
 *             cream brand tint; the filled brand brown stays for selection and primary actions only.
 */
export type BadgeTone = "success" | "neutral" | "warning" | "negative" | "brand";

export const BADGE_BASE = "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-bold leading-4";

export const BADGE_TONE: Record<BadgeTone, string> = {
  success: "bg-pos-tint text-pos-ink",
  neutral: "bg-ground text-muted ring-1 ring-inset ring-border",
  warning: "bg-warn-bg text-warn-ink",
  negative: "bg-neg-tint text-neg-ink",
  brand: "bg-teal-tint text-teal-dark",
};

/** The badge's classes, for an element that is already a <span>, <li> or similar. */
export function badgeClass(tone: BadgeTone, extra = ""): string {
  return `${BADGE_BASE} ${BADGE_TONE[tone]}${extra ? ` ${extra}` : ""}`;
}

export default function StatusBadge({
  tone,
  className = "",
  children,
  ...rest
}: {
  tone: BadgeTone;
  className?: string;
  children: ReactNode;
} & Omit<HTMLAttributes<HTMLSpanElement>, "className" | "children">) {
  return (
    <span className={badgeClass(tone, className)} {...rest}>
      {children}
    </span>
  );
}
