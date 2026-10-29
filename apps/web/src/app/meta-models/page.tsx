import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import { measured, metaModels, STANDARD_SPARK, type MetaModel, type Result } from "@/lib/meta-models-page";

export const metadata = { title: "Meta models in Accnomos · Accnomos" };

const CHECKED = "29 Oct 2026";

function ResultLine({ r }: { r: Result }) {
  return (
    <li className="text-[14px] leading-6">
      <span className="font-semibold">{r.label}:</span> {r.value}{" "}
      <span className="text-muted">({r.basis})</span>
      {r.report ? (
        <>
          {" "}
          <a href={r.report} className="font-semibold text-teal-dark underline underline-offset-2 hover:text-teal">
            Report<span className="sr-only">: {r.report.replace(/^.*\/blob\/main\//, "")}</span>
          </a>
        </>
      ) : null}
    </li>
  );
}

/** The overview: a table from 768 px, the same rows as stacked cards below that. */
function Overview({ models }: { models: MetaModel[] }) {
  const label = "Meta models used in Accnomos";
  return (
    <>
      <table aria-label={label} className="hidden w-full border-collapse overflow-hidden rounded-2xl bg-white text-left text-[14px] leading-6 md:table">
        <thead className="bg-teal-tint text-teal-dark">
          <tr>
            <th scope="col" className="p-3 font-extrabold">Model</th>
            <th scope="col" className="p-3 font-extrabold">What it does in Accnomos</th>
            <th scope="col" className="p-3 font-extrabold">How it is called</th>
            <th scope="col" className="p-3 font-extrabold">Measured</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id} data-testid={`row-${m.id}`} className="border-t border-border align-top">
              <th scope="row" className="p-3 font-bold">
                <a href={`#${m.id}`} className="text-teal-dark underline underline-offset-2 hover:text-teal">
                  {m.name}
                </a>
                <span className="block font-mono text-[12px] font-normal text-muted">{m.modelId}</span>
              </th>
              <td className="p-3">{m.uses}</td>
              <td className="p-3">{m.via}</td>
              <td className="p-3">{measured(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul aria-label={label} className="flex flex-col gap-3 md:hidden">
        {models.map((m) => (
          <li key={m.id} data-testid={`card-${m.id}`} className="rounded-2xl border border-border bg-white p-4">
            <p className="font-bold">
              <a href={`#${m.id}`} className="text-teal-dark underline underline-offset-2 hover:text-teal">
                {m.name}
              </a>
            </p>
            <p className="break-all font-mono text-[12px] text-muted">{m.modelId}</p>
            <p className="mt-2 text-[14px] leading-6">{m.uses}</p>
            <p className="mt-1 text-[14px] leading-6 text-muted">{m.via}</p>
            <p className="mt-1 text-[14px] leading-6">
              <span className="font-semibold">Measured:</span> {measured(m)}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}

function Detail({ m }: { m: MetaModel }) {
  const h = `${m.id}-title`;
  const sub = "mt-4 text-[13px] font-extrabold uppercase tracking-[0.06em] text-teal-dark";
  return (
    <section id={m.id} aria-labelledby={h} data-testid={`model-${m.id}`} className="scroll-mt-24 rounded-2xl border border-border bg-white p-4 sm:p-6">
      <h2 id={h} className="text-xl font-extrabold tracking-tight">
        {m.name}
      </h2>
      <p className="break-all font-mono text-[12px] text-muted">{m.modelId}</p>
      <p className="mt-2 text-[15px] leading-7">{m.what}</p>

      <h3 className={sub}>Jobs, and where you see them</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] leading-6">
        {m.jobs.map((j) => (
          <li key={j.job}>
            {j.job} <span className="text-muted">— {j.screen}</span>
          </li>
        ))}
      </ul>

      <h3 className={sub}>How it is called</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] leading-6">
        {m.called.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <h3 className={sub}>What code checks after it</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] leading-6">
        {m.checks.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <h3 className={sub}>Measured</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {m.results.map((r) => (
          <ResultLine key={r.label} r={r} />
        ))}
      </ul>
    </section>
  );
}

export default function MetaModelsPage() {
  // Read from evals/runs/*/summary.json when the site is built: the numbers are the committed runs', not typed in.
  const models = metaModels();
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Meta models in Accnomos"
        description="Which Meta model does which job, where you see it in the app, how it is called, what code checks after it, and how it scored on our test sets."
      />
      <p className="text-[15px] leading-7">
        The rule everywhere: <strong>AI proposes, you approve, code calculates.</strong> A model reads or words things;
        code works out every amount in pence and checks what the model said; nothing is posted or sent until you
        approve it. The test sets are made-up documents, so real phone photos will score lower. Checked against the code
        on {CHECKED}.
      </p>
      <p data-testid="live-order" className="rounded-2xl border border-teal/30 bg-teal-tint p-4 text-[15px] leading-7">
        <strong>On our live server</strong> the Meta Model API (Muse Spark) answers first and a local fallback model
        answers last. <strong>{STANDARD_SPARK}</strong>
      </p>
      <Overview models={models} />
      {models.map((m) => (
        <Detail key={m.id} m={m} />
      ))}
      <p className="text-[14px] leading-6 text-muted">
        No other Meta model is called. Every figure above is read from the committed eval runs when this site is built.
        See also{" "}
        <Link href="/how-it-works" className="font-semibold text-teal-dark underline underline-offset-2 hover:text-teal">
          how each feature works
        </Link>
        .
      </p>
    </div>
  );
}
