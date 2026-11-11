/**
 * The help centre's articles (src/content/help/articles.json, the one source). Each article's `id` is stable: it is the
 * page (/help/<id>) and what the support assistant cites (services/runtime/app/support/help.py reads a copy made by
 * tools/sync_help_articles.py; the runtime's tests fail when the copy differs). Pure: the unit tests import it alone.
 */
import data from "../content/help/articles.json";

export interface HelpStep {
  title: string;
  body: string;
  image?: string;
  alt?: string;
}
export interface HelpArticle {
  id: string;
  title: string;
  summary: string;
  category: string;
  platforms: string[];
  keywords: string[];
  steps: HelpStep[];
  troubleshooting: { problem: string; fix: string }[];
  related: string[];
}
export interface HelpCategory {
  id: string;
  title: string;
}

export const HELP_UPDATED: string = data.updated;
export const HELP_CATEGORIES: HelpCategory[] = data.categories;
export const HELP_ARTICLES: HelpArticle[] = data.articles as HelpArticle[];

export const helpArticle = (id: string): HelpArticle | undefined => HELP_ARTICLES.find((a) => a.id === id);
export const helpPath = (id: string) => `/help/${id}`;

/** A citation the runtime gives as `help:<id>` (POST /books/ask), or null for a file path. */
export function helpCitation(citation: string): HelpArticle | null {
  return citation.startsWith("help:") ? (helpArticle(citation.slice(5)) ?? null) : null;
}

/** The help centre's own search box: every word must appear in the title, summary, keywords or steps. */
export function searchHelp(query: string): HelpArticle[] {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  if (!words.length) return HELP_ARTICLES;
  return HELP_ARTICLES.filter((a) => {
    const hay = [a.title, a.summary, a.keywords.join(" "), ...a.steps.map((s) => `${s.title} ${s.body}`)].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** **bold** and [text](/path) only: the articles' own markup. */
export type Inline = { kind: "text" | "bold"; text: string } | { kind: "link"; text: string; href: string };
export function inlineParts(text: string): Inline[] {
  const out: Inline[] = [];
  const re = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ kind: "bold", text: m[1] });
    else out.push({ kind: "link", text: m[2], href: m[3] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
