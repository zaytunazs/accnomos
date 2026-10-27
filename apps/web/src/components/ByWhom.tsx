interface ByWhomProps {
  /** What code did (or the standing rule, e.g. "Nothing sent"). Rendered first. */
  code: string;
  /** What the AI did — or "no AI involved", or what you did ("rules by you"). Rendered second. */
  ai: string;
  /** Extra spacing for the call site, e.g. "mt-3". */
  className?: string;
}

/**
 * One tiny muted "who did what" line for every card and section that mixes the
 * two: what code did · what the AI (or you) did. Wording is reused from the
 * page copy and /how-it-works; see docs/HONESTY.md before inventing new claims.
 */
export default function ByWhom({ code, ai, className = "" }: ByWhomProps) {
  return (
    <p className={`text-[12px] leading-5 text-muted${className ? ` ${className}` : ""}`}>
      {code} · {ai}
    </p>
  );
}
