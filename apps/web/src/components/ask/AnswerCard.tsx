import Link from "next/link";
import type { ReactNode } from "react";
import type { RtAskAnswer, RtSuggestedAction } from "@/lib/runtime";

/** **bold** and `code` inside one line; everything else stays text (React escapes it). */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return (
        <code key={i} className="rounded bg-ground px-1 text-[0.95em]">
          {part.slice(1, -1)}
        </code>
      );
    return part;
  });
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul" | "ol"; items: string[] };
const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;

/** Plain markdown → paragraphs and lists. Headings become bold paragraphs; nothing else is interpreted. */
function blocks(md: string): Block[] {
  const out: Block[] = [];
  for (const raw of md.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const last = out[out.length - 1];
    const listKind = BULLET.test(line) ? "ul" : NUMBERED.test(line) ? "ol" : null;
    if (!line.trim()) {
      out.push({ kind: "p", lines: [] }); // paragraph break; empty blocks are dropped below
    } else if (listKind) {
      const item = line.replace(listKind === "ul" ? BULLET : NUMBERED, "");
      if (last?.kind === listKind) last.items.push(item);
      else out.push({ kind: listKind, items: [item] });
    } else {
      const text = /^#{1,6}\s/.test(line) ? `**${line.replace(/^#+\s*/, "")}**` : line.trim();
      if (last?.kind === "p" && last.lines.length) last.lines.push(text);
      else out.push({ kind: "p", lines: [text] });
    }
  }
  return out.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export function Markdown({ md }: { md: string }) {
  return (
    <div className="flex flex-col gap-2 text-[15px] leading-7">
      {blocks(md).map((b, i) =>
        b.kind === "p" ? (
          <p key={i}>{inline(b.lines.join(" "))}</p>
        ) : b.kind === "ul" ? (
          <ul key={i} className="ml-5 list-disc">
            {b.items.map((it, j) => (
              <li key={j}>{inline(it)}</li>
            ))}
          </ul>
        ) : (
          <ol key={i} className="ml-5 list-decimal">
            {b.items.map((it, j) => (
              <li key={j}>{inline(it)}</li>
            ))}
          </ol>
        ),
      )}
    </div>
  );
}

const ACTION_HREF: Record<RtSuggestedAction["kind"], string | null> = {
  open_review: "/review",
  chase_supplier: "/review",
  open_vat: "/vat",
  plan_day: "/", // Home opens the plan for ?plan=YYYY-MM-DD
  none: null,
};

function actionHref(a: RtSuggestedAction): string | null {
  if (a.kind === "plan_day") return a.arg && /^\d{4}-\d{2}-\d{2}$/.test(a.arg) ? `/?plan=${a.arg}` : null;
  return ACTION_HREF[a.kind];
}

/** One checked answer: words, key numbers, cited files and next steps. */
export default function AnswerCard({ answer }: { answer: RtAskAnswer }) {
  const actions = answer.suggested_actions.filter((a) => actionHref(a));
  return (
    <article className="rounded-2xl border border-border bg-white p-5">
      {answer.fallback_reason && (
        <p className="mb-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink">
          {answer.fallback_reason} These figures come straight from your ledger.
        </p>
      )}
      <Markdown md={answer.answer_md} />

      {answer.key_numbers.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2" aria-label="Key numbers">
          {answer.key_numbers.map((k) => (
            <li
              key={`${k.label}-${k.value}`}
              title={`From ${k.source}`}
              className="flex items-baseline gap-2 rounded-full bg-teal-tint px-3 py-1.5 text-[13px]"
            >
              <span className="text-muted">{k.label}</span>
              <span className="font-extrabold tabular-nums text-teal-dark">{k.value}</span>
            </li>
          ))}
        </ul>
      )}

      {answer.citations.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Files used">
          {answer.citations.map((c) => (
            <li key={c} className="rounded-lg border border-border bg-ground px-2.5 py-1 font-mono text-[12px] text-muted">
              {c}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-[13px] text-muted">
        {answer.model === "code" ? "Worked out by code" : <>Numbers by code · words by {answer.model}</>}
        {answer.confidence !== "high" && ` · confidence ${answer.confidence}`}
      </p>

      {actions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((a) => (
            <Link
              key={`${a.kind}-${a.label}`}
              href={actionHref(a)!}
              className="flex h-10 items-center rounded-full border border-teal px-4 text-[14px] font-bold text-teal hover:bg-teal-tint"
            >
              {a.label}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}
