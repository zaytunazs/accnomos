import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import ByWhom from "@/components/ByWhom";
import type { AccountInfo } from "@azure/msal-browser";
import { shortModelName } from "@/lib/ai-config";
import { getFileWebUrl } from "@/lib/graph";
import { helpCitation } from "@/lib/help";
import type { RtAskAnswer, RtSuggestedAction } from "@/lib/runtime";

/**
 * **bold**, *emphasis*, `code` and [links](/help/…) inside one line; everything else stays text (React escapes it). Only
 * links to our own pages (a path starting with one "/") become links: the help centre's answers cite their article.
 */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(\/[^)\s/][^)\s]*\)|\*[^*\s][^*]*\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>;
    const link = /^\[([^\]]+)\]\((\/[^)\s]*)\)$/.exec(part);
    if (link)
      return (
        <Link key={i} href={link[2]} className="font-bold text-teal-dark underline underline-offset-2">
          {link[1]}
        </Link>
      );
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) return <em key={i}>{part.slice(1, -1)}</em>;
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
  open_spending: "/spending",
  open_help: "/help",
  open_support: "/support",
  none: null,
};

function actionHref(a: RtSuggestedAction): string | null {
  if (a.kind === "plan_day") return a.arg && /^\d{4}-\d{2}-\d{2}$/.test(a.arg) ? `/?plan=${a.arg}` : null;
  if (a.kind === "open_help") return a.arg && /^[a-z0-9-]+$/.test(a.arg) ? `/help/${a.arg}` : "/help";
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
  "inline-block max-w-full break-words rounded-lg border border-border bg-ground px-2.5 py-1 text-[12px] text-muted hover:border-teal hover:text-teal-dark";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10" → "Oct 2026". */
function monthLabel(ym: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  return m ? `${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : ym;
}

/** A cited file, grouped: ledger events of one month become one chip; the paths stay in the tooltip. */
export interface CitationGroup {
  label: string; // what the chip says
  paths: string[]; // every file behind it, in the answer's order
}

/** The `_System` files by what they are; anything else by its own name (a receipt, a statement, Books.xlsx). */
function systemFileLabel(path: string): string {
  const m = /^_System\/([^/]+)(?:\/([^/]+))?/.exec(path);
  if (!m) return path;
  switch (m[1]) {
    case "Contacts":
      return "Contacts";
    case "Jobs":
    case "Staff":
    case "Timesheets":
      return "Jobs and timesheets";
    case "proposals":
      return "A document waiting in Review";
    case "Payroll":
      return "Payroll run";
    case "Vehicles":
    case "Mileage":
      return "Vehicles and mileage";
    case "vat":
      return "VAT";
    case "Todos":
      return "To-dos";
    case "Rules":
      return "Autopilot rules";
    case "Invoices":
    case "invoices":
      return "Invoices";
    default:
      return path.split("/").pop() ?? path;
  }
}

/**
 * Chips the reader can take in at a glance: "Ledger · Oct 2026 (3 entries)" rather than five event file names
 * (`_System/Ledger/events/2026-10/<stamp>-runtime-<hash>.json`); each chip's tooltip lists every path, and the chip
 * opens the first file (signed in) or the Files page. Books.xlsx keeps its sheet name.
 */
export function groupCitations(citations: string[], sheet: string): CitationGroup[] {
  const groups: CitationGroup[] = [];
  const ledger = new Map<string, CitationGroup>();
  for (const c of citations) {
    const path = c.replace(/\/+$/, "");
    const ev = /^_System\/Ledger\/events\/(\d{4}-\d{2})(?:\/|$)/.exec(path); // a month folder, or one event file in it
    if (ev) {
      const g = ledger.get(ev[1]);
      if (g) g.paths.push(path);
      else {
        const made = { label: `Ledger · ${monthLabel(ev[1])}`, paths: [path] };
        ledger.set(ev[1], made);
        groups.push(made);
      }
      continue;
    }
    const paypal = /^paypal:([A-Za-z0-9-]{1,64})$/.exec(path); // AI search: a PayPal transaction, synced or not
    if (paypal) {
      groups.push({ label: `PayPal · ${paypal[1]}`, paths: [path] });
      continue;
    }
    const invoice = /^invoice:([A-Za-z0-9/_.-]{1,40})$/.exec(path);
    if (invoice) {
      groups.push({ label: `Invoice ${invoice[1]}`, paths: [path] });
      continue;
    }
    if (path === "Books.xlsx") {
      groups.push({ label: `Books.xlsx · ${sheet} sheet`, paths: [path] });
      continue;
    }
    groups.push({ label: path.startsWith("_System/") ? systemFileLabel(path) : path, paths: [path] });
  }
  for (const g of ledger.values()) {
    const files = g.paths.filter((x) => x.endsWith(".json")).length;
    if (files > 1) g.label = `${g.label} (${files} entries)`;
  }
  return groups;
}

/** AI search cites PayPal transactions (`paypal:<id>`) and invoices (`invoice:<number>`): they open in the app. */
export function citationPage(c: string): { href: string; title: string } | null {
  if (/^paypal:[A-Za-z0-9-]{1,64}$/.test(c)) return { href: "/invoices#paypal-sync", title: "Open Sync PayPal on Invoices" };
  const inv = /^invoice:([A-Za-z0-9/_.-]{1,40})$/.exec(c);
  if (inv) return { href: `/invoices?q=${encodeURIComponent(inv[1])}`, title: `Open invoice ${inv[1]}` };
  return null;
}

/** One cited file (or a month of ledger entries): its Graph web URL when signed in, otherwise the Files page. */
function CitationChip({ group, account }: { group: CitationGroup; account: AccountInfo | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const first = group.paths[0];
  const help = helpCitation(first);
  useEffect(() => {
    if (!account || help || citationPage(first)) return;
    let stale = false;
    void getFileWebUrl(account, first).then((u) => {
      if (!stale) setUrl(u);
    });
    return () => {
      stale = true;
    };
  }, [account, first, help]);
  if (help)
    return (
      <Link href={`/help/${help.id}`} title={`Help article: ${help.title}`} className={chip}>
        Help · {help.title}
      </Link>
    );
  const page = citationPage(first);
  if (page)
    return (
      <Link href={page.href} title={page.title} className={chip}>
        {group.label}
      </Link>
    );
  const label = group.label;
  const title = group.paths.length > 1 ? `${group.paths.join("\n")} — open the first` : `Open ${first}`;
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
        <div className="relative mt-4 overflow-x-auto">
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
          {groupCitations(answer.citations, sheet).map((g) => (
            <li key={g.paths[0]} className="min-w-0 max-w-full">
              <CitationChip group={g} account={account} />
            </li>
          ))}
        </ul>
      )}

      {(() => {
        const suffix = `${!pending && answer.confidence !== "high" ? ` · confidence ${answer.confidence}` : ""}${elapsed}`;
        if (pending)
          return (
            <ByWhom
              className="mt-3"
              code="Numbers by code"
              ai={`${shortModelName(answer.model)} is writing the explanation; every figure in it is checked before it stays${suffix}`}
            />
          );
        if (answer.model === "code") return <p className="mt-3 text-[13px] text-muted">Worked out by code{suffix}</p>;
        return <ByWhom className="mt-3" code="Numbers by code" ai={`explanation by ${shortModelName(answer.model)}${suffix}`} />;
      })()}

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
