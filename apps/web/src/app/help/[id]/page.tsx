import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import Rich from "@/components/support/Rich";
import { HELP_ARTICLES, HELP_CATEGORIES, HELP_UPDATED, helpArticle } from "@/lib/help";

const SITE = "https://accnomos.com";

export const dynamicParams = false;

export function generateStaticParams() {
  return HELP_ARTICLES.map((a) => ({ id: a.id }));
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const a = helpArticle((await params).id);
  if (!a) return { title: "Help · Accnomos" };
  return {
    title: `${a.title} · Help · Accnomos`,
    description: a.summary,
    alternates: { canonical: `/help/${a.id}` },
    openGraph: { title: a.title, description: a.summary, url: `${SITE}/help/${a.id}`, ...(a.steps.find((s) => s.image) ? { images: [`${SITE}${a.steps.find((s) => s.image)!.image}`] } : {}) },
  };
}

const plain = (text: string) => text.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");

/** One help article: numbered steps with screenshots, "If this goes wrong", related articles; HowTo structured data. */
export default async function HelpArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const a = helpArticle((await params).id);
  if (!a) notFound();
  const category = HELP_CATEGORIES.find((c) => c.id === a.category)?.title ?? "Help";
  const ld = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: a.title,
    description: a.summary,
    url: `${SITE}/help/${a.id}`,
    dateModified: HELP_UPDATED,
    step: a.steps.map((s, i) => ({
      "@type": "HowToStep",
      position: i + 1,
      name: s.title,
      text: plain(s.body),
      ...(s.image ? { image: `${SITE}${s.image}` } : {}),
    })),
  };
  return (
    <article className="flex flex-col" data-help-article={a.id}>
      <nav aria-label="Breadcrumb" className="text-sm text-muted">
        <Link href="/help" className="font-bold text-teal-dark underline underline-offset-2">
          Help centre
        </Link>{" "}
        › {category}
      </nav>
      <h1 className="mt-2 text-3xl font-extrabold tracking-tight">{a.title}</h1>
      <p className="mt-1 text-[15px] leading-7 text-muted">{a.summary}</p>
      <p className="mt-1 text-[13px] text-muted">
        {a.platforms.map((p) => (p === "android" ? "Android app" : "Web")).join(" and ")} · updated {new Date(`${HELP_UPDATED}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}
      </p>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(ld) }} />

      <ol className="mt-6 flex flex-col gap-5" aria-label="Steps">
        {a.steps.map((s, i) => (
          <li key={s.title} className="rounded-2xl border border-border bg-white p-4 sm:p-5">
            <h2 className="flex items-baseline gap-3 text-[17px] font-extrabold">
              <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-teal text-[14px] text-white">
                {i + 1}
              </span>
              <span>
                <span className="sr-only">Step {i + 1}: </span>
                {s.title}
              </span>
            </h2>
            <p className="mt-2 text-[15px] leading-7">
              <Rich text={s.body} />
            </p>
            {s.image && (
              // eslint-disable-next-line @next/next/no-img-element -- static export; the screenshots are already sized webp
              <img src={s.image} alt={s.alt ?? ""} loading={i === 0 ? "eager" : "lazy"} width={1280} height={800} className="mt-3 h-auto w-full rounded-xl border border-border" />
            )}
          </li>
        ))}
      </ol>

      {a.troubleshooting.length > 0 && (
        <section aria-labelledby="trouble" className="mt-6 rounded-2xl border border-warn-border bg-warn-bg p-4 text-warn-ink">
          <h2 id="trouble" className="text-[17px] font-extrabold">
            If this goes wrong
          </h2>
          <dl className="mt-2 flex flex-col gap-2 text-[15px] leading-7">
            {a.troubleshooting.map((t) => (
              <div key={t.problem}>
                <dt className="font-bold">{t.problem}</dt>
                <dd>
                  <Rich text={t.fix} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section aria-labelledby="still" className="mt-6 rounded-2xl border border-border bg-white p-4">
        <h2 id="still" className="text-[15px] font-extrabold">
          Still stuck?
        </h2>
        <p className="mt-1 text-sm">
          <Link href={`/support?article=${a.id}`} className="font-bold text-teal-dark underline underline-offset-2">
            Ask the support assistant or raise a ticket
          </Link>{" "}
          (signed in).
        </p>
      </section>

      {a.related.length > 0 && (
        <section aria-labelledby="related" className="mt-6">
          <h2 id="related" className="text-[15px] font-extrabold">
            Related guides
          </h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {a.related.map((id) => {
              const r = helpArticle(id);
              return r ? (
                <li key={id}>
                  <Link href={`/help/${id}`} className="inline-flex h-10 items-center rounded-full border border-teal px-4 text-[14px] font-bold text-teal hover:bg-teal-tint">
                    {r.title}
                  </Link>
                </li>
              ) : null;
            })}
          </ul>
        </section>
      )}
    </article>
  );
}
