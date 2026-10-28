"use client";

import { useCallback, useEffect, useState } from "react";
import { RetryButton } from "@/components/States";
import type { EvalHeadline } from "@/lib/evals";
import {
  aiCalls,
  aiHealth,
  metaModelName,
  providerLabel,
  warmServerAi,
  type AiCall,
  type AiHealth,
  type ProviderHealth,
} from "@/lib/meta-models";

const card = "rounded-2xl border border-border bg-white p-4 sm:p-6";
const heading = "text-lg font-extrabold tracking-tight";

const TASKS: Record<string, string> = {
  extract: "Read a document",
  verify: "Second reading",
  ask_answer: "Ask answer",
  plan_rationale: "Plan for the day",
  mail_triage: "Inbox triage",
  payment_reminder: "Payment reminder",
  action_intent: "Ask instruction",
  bank_coding: "Bank line coding",
  duplicate: "Duplicate contacts",
};

const STATUS: Record<ProviderHealth["status"], { text: string; tone: string }> = {
  up: { text: "Up", tone: "bg-teal-tint text-teal-dark" },
  warm: { text: "Warm", tone: "bg-teal-tint text-teal-dark" },
  idle: { text: "Idle (starts on the next call)", tone: "bg-ground text-muted" },
  down: { text: "Down", tone: "border border-warn-border bg-warn-bg text-warn-ink" },
  "not configured": { text: "Not configured", tone: "bg-ground text-muted" },
};

const seconds = (ms: number) => `${ms < 10_000 ? (ms / 1000).toFixed(1) : Math.round(ms / 1000)} s`;
const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Chain({ health }: { health: AiHealth }) {
  if (health.chain.length === 0) {
    return (
      <p className="mt-2 text-[15px] leading-7 text-muted">
        This server has no provider chain set (AI_PROVIDERS), so every call goes to its single default model.
      </p>
    );
  }
  return (
    <ol aria-label="Provider chain" className="mt-3 flex flex-col gap-3">
      {health.providers.map((p, i) => {
        const s = STATUS[p.status] ?? STATUS.down;
        return (
          <li key={p.name} data-testid={`provider-${p.name}`} className="rounded-xl border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-bold text-muted">{i === 0 ? "1st" : i === 1 ? "2nd" : `${i + 1}th`}</span>
              <span className="text-[15px] font-extrabold">
                {metaModelName(p.model)} · {p.label}
              </span>
              <span className={`rounded-full px-3 py-0.5 text-[13px] font-bold ${s.tone}`}>{s.text}</span>
              {p.circuit === "open" && (
                <span className="rounded-full border border-warn-border bg-warn-bg px-3 py-0.5 text-[13px] font-bold text-warn-ink">
                  Skipped for {p.retry_in_s ?? 0} s
                </span>
              )}
            </div>
            <p className="mt-1 break-words text-[14px] text-muted">
              {p.detail}
              {p.probe_ms !== null ? ` · answered in ${p.probe_ms} ms` : ""}
            </p>
            <p className="mt-1 text-[13px] text-muted">
              Reads images: {p.vision ? "yes" : "no"} · Strict JSON: {p.json_mode ? "yes" : "no"} · Voice:{" "}
              {p.voice ? "yes (Muse Voice Transcribe)" : "no"}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

function Calls({ calls }: { calls: AiCall[] }) {
  if (calls.length === 0) {
    return <p className="mt-2 text-[15px] text-muted">No AI calls since the server last started.</p>;
  }
  return (
    // Focusable and named, so a keyboard user can scroll it sideways on a phone.
    <div role="region" aria-label="Recent AI calls table" tabIndex={0} className="mt-3 overflow-x-auto">
      <table aria-label="Recent AI calls" className="w-full min-w-[520px] text-left text-[14px]">
        <thead>
          <tr className="text-[13px] text-muted">
            <th className="py-1 pr-3 font-semibold">Time</th>
            <th className="py-1 pr-3 font-semibold">Task</th>
            <th className="py-1 pr-3 font-semibold">Model</th>
            <th className="py-1 pr-3 font-semibold">Time taken</th>
            <th className="py-1 font-semibold">Fell back?</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c, i) => (
            <tr key={`${c.at}-${i}`} className="border-t border-border">
              <td className="py-1.5 pr-3 tabular-nums">{clock(c.at)}</td>
              <td className="py-1.5 pr-3">{TASKS[c.task] ?? c.task}</td>
              <td className="py-1.5 pr-3">
                {metaModelName(c.model)} ({providerLabel(c.provider)})
                {!c.ok && <span className="font-bold text-warn-ink"> · failed: {c.error ?? "error"}</span>}
              </td>
              <td className="py-1.5 pr-3 tabular-nums">{seconds(c.latency_ms)}</td>
              <td className="py-1.5">{c.fell_back_from.length ? `yes, from ${c.fell_back_from.map(providerLabel).join(", ")}` : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Evals({ evals }: { evals: EvalHeadline[] }) {
  return (
    <ul className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
      {evals.map((e) => (
        <li key={e.run} className="rounded-xl border border-border p-3">
          <p className="text-[15px] font-extrabold">{e.title}</p>
          <p className="text-[13px] font-semibold text-muted">
            {e.model} · {e.where}
          </p>
          <dl className="mt-2 grid grid-cols-2 gap-2">
            {e.numbers.map((n) => (
              <div key={n.label}>
                <dt className="text-[12px] font-semibold text-muted">{n.label}</dt>
                <dd className="text-[15px] font-bold tabular-nums">{n.value}</dd>
              </div>
            ))}
          </dl>
          <a href={e.report} className="mt-2 inline-block text-[14px] font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
            Report: evals/runs/{e.run}
          </a>
        </li>
      ))}
    </ul>
  );
}

export default function ModelsAtWork({ evals }: { evals: EvalHeadline[] }) {
  const [health, setHealth] = useState<AiHealth | null>(null);
  const [calls, setCalls] = useState<AiCall[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [h, c] = await Promise.all([aiHealth(), aiCalls()]);
      setHealth(h);
      setCalls(c);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    warmServerAi();
    (async () => {
      try {
        const [h, c] = await Promise.all([aiHealth(), aiCalls()]);
        setHealth(h);
        setCalls(c);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  return (
    <div className="mt-5 flex flex-col gap-4">
      <section aria-labelledby="models-chain" className={card}>
        <h2 id="models-chain" className={heading}>
          The chain
        </h2>
        <p className="mt-1 text-sm text-muted">
          Each AI call goes to the first provider that is up; if it times out, errors or is out of credit, the next
          one takes the call. All three serve Meta models. If you chose your own AI in Settings, your calls go only
          there.
        </p>
        {error && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-[15px] text-warn-ink">
            <span>The runtime did not answer ({error}).</span>
            <RetryButton
              onRetry={() => {
                setError(null);
                void load();
              }}
            />
          </div>
        )}
        {!error && !health && <p className="mt-3 text-[15px] text-muted">Checking each provider…</p>}
        {health && <Chain health={health} />}
      </section>

      <section aria-labelledby="models-calls" className={card}>
        <h2 id="models-calls" className={heading}>
          Last AI calls
        </h2>
        <p className="mt-1 text-sm text-muted">
          The last 50 calls this server made, from memory only (a restart empties it). No document or question
          content is kept.
        </p>
        {calls && <Calls calls={calls} />}
      </section>

      <section aria-labelledby="models-evals" className={card}>
        <h2 id="models-evals" className={heading}>
          How they scored
        </h2>
        <p className="mt-1 text-sm text-muted">
          From the committed eval runs, on made-up documents: real phone photos will score lower.
        </p>
        <Evals evals={evals} />
      </section>
    </div>
  );
}
