import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { getFileWebUrl } from "@/lib/graph";
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

/**
 * Which Books.xlsx sheet an answer's figures live on, from the cited paths.
 * The workbook is a projection (see services/runtime/app/projection.py); VAT
 * answers cite both the returns and the ledger folders, so VAT wins.
 */
export function workbookSheet(answer: RtAskAnswer): string {
  const hay = [...answer.key_numbers.map((k) => k.source), ...answer.citations].join("\n");
  if (hay.includes("VAT returns")) return "VAT";
  if (hay.includes("Bank statements")) return "Bank";
  if (hay.includes("_System/proposals") || hay.includes("02 Needs a look")) return "Proposals";
  if (hay.includes("/Jobs") || hay.includes("/Staff") || hay.includes("/Timesheets")) return "Jobs";
  if (hay.includes("/Vehicles") || hay.includes("/Mileage")) return "Vehicles";
  if (hay.includes("/Payroll")) return "Payroll";
  if (hay.includes("/contacts")) return "Customers";
  if (hay.includes("_System/Ledger")) return "Ledger";
  return "Summary";
}

const chip =
  "inline-block max-w-full break-words rounded-lg border border-border bg-ground px-2.5 py-1 font-mono text-[12px] text-muted hover:border-teal hover:text-teal-dark";

/** One cited file: its Graph web URL when signed in, otherwise the Files page. */
function CitationChip({ citation, sheet, account }: { citation: string; sheet: string | null; account: AccountInfo | null }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!account) return;
    let stale = false;
    void getFileWebUrl(account, citation.replace(/\/+$/, "")).then((u) => {
      if (!stale) setUrl(u);
    });
    return () => {
      stale = true;
    };
  }, [account, citation]);
  const label = sheet ? `${citation} · ${sheet} sheet` : citation;
  const title = sheet ? `${citation}, ${sheet} sheet — open the file` : `Open ${citation}`;
  if (url) {
    return (
      <a href={url} target="_blank" rel="noreferrer" title={title} className={chip}>
        {label}
      </a>
    );
  }
  return (
    <Link href="/files" title={title} className={chip}>
      {label}
    </Link>
  );
}

/** One checked answer: words, key numbers, cited files and next steps. */
export default function AnswerCard({
  answer,
  account = null,
  elapsedS = null,
  pending = false,
}: {
  answer: RtAskAnswer;
  account?: AccountInfo | null;
  /** How long the answer took, timed around the ask call. */
  elapsedS?: number | null;
  /** Streaming: the key numbers are code's already; the words are still being written and are not yet checked. */
  pending?: boolean;
}) {
  const actions = answer.suggested_actions.filter((a) => actionHref(a));
  const sheet = workbookSheet(answer);
  const elapsed = elapsedS !== null && Number.isFinite(elapsedS) ? ` · ${elapsedS < 10 ? elapsedS.toFixed(1) : Math.round(elapsedS)} s` : "";
  return (
    <article className="min-w-0 rounded-2xl border border-border bg-white p-5" aria-busy={pending || undefined}>
      {answer.fallback_reason && (
        <p className="mb-3 rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink">
          {answer.fallback_reason} These figures come straight from your ledger.
        </p>
      )}
      {pending && !answer.answer_md ? (
        <p className="text-[15px] leading-7 text-muted">Writing the explanation…</p>
      ) : (
        <Markdown md={answer.answer_md} />
      )}

      {answer.key_numbers.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-[13px] leading-6">
            <caption className="sr-only">Key numbers</caption>
            <tbody>
              {answer.key_numbers.map((k) => (
                <tr key={`${k.label}-${k.value}`} title={`From ${k.source}`} className="border-b border-border last:border-b-0">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium text-muted">
                    {k.label}
                  </th>
                  <td className="whitespace-nowrap py-1.5 text-right font-extrabold tabular-nums text-teal-dark">{k.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {answer.citations.length > 0 && (
        <ul className="mt-3 flex min-w-0 flex-wrap gap-2" aria-label="Files used">
          {answer.citations.map((c) => (
            <li key={c} className="min-w-0 max-w-full">
              <CitationChip citation={c} sheet={c === "Books.xlsx" ? sheet : null} account={account} />
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-[13px] text-muted">
        {pending ? (
          <>Numbers by code · {answer.model} is writing the explanation; every figure in it is checked before it stays</>
        ) : answer.model === "code" ? (
          "Worked out by code"
        ) : (
          <>Numbers by code · explanation by {answer.model}</>
        )}
        {!pending && answer.confidence !== "high" && ` · confidence ${answer.confidence}`}
        {elapsed}
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
