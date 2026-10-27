"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { loadAiConfig, RUNTIME_URL } from "@/lib/ai-config";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, runtimeHealth, type RtAskAnswer, type RtAskTurn } from "@/lib/runtime";
import { sampleAnswer, sampleQuestion } from "@/lib/sample-ask";
import AnswerCard from "./AnswerCard";
import MicButton from "./MicButton";

interface Turn {
  question: string; // empty while a spoken question is being transcribed
  answer?: RtAskAnswer;
  error?: string;
}

type Mode = "loading" | "sample" | "live";

function Question({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      {text ? (
        <p className="max-w-[min(32rem,85%)] rounded-2xl bg-teal px-4 py-3 text-[15px] leading-6 text-white">{text}</p>
      ) : (
        <p className="rounded-2xl bg-teal/70 px-4 py-3 text-[15px] italic leading-6 text-white">Transcribing…</p>
      )}
    </div>
  );
}

/** Live answers from POST /books/ask when signed in and the runtime answers; otherwise the sample thread. */
export default function AskThread() {
  const [mode, setMode] = useState<Mode>("loading");
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [offline, setOffline] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const [voiceOff, setVoiceOff] = useState<string | null>("Sign in to ask by voice");
  const end = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  function historyOf(before: Turn[]): RtAskTurn[] {
    return before
      .filter((t) => t.answer)
      .flatMap((t) => [
        { role: "user" as const, text: t.question },
        { role: "assistant" as const, text: t.answer!.answer_md },
      ]);
  }

  async function ask(question: string, acct: AccountInfo, before: Turn[]) {
    const q = question.trim();
    if (!q) return;
    const history = historyOf(before);
    setTurns([...before, { question: q }]);
    setInput("");
    setBusy(true);
    try {
      const answer = await runtime.ask(acct, q, null, history);
      setTurns([...before, { question: q, answer }]);
    } catch (e) {
      setTurns([...before, { question: q, error: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
    }
  }

  /** A spoken question: "Transcribing…" bubble, then the transcript replaces it and the answer renders as usual. */
  async function askVoice(audio: Blob, acct: AccountInfo, before: Turn[]) {
    setTurns([...before, { question: "" }]);
    setBusy(true);
    try {
      const { transcript, ...answer } = await runtime.askVoice(acct, audio, null, historyOf(before));
      setTurns([...before, { question: transcript, answer }]);
    } catch (e) {
      setTurns([...before, { question: "(voice question)", error: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    (async () => {
      const q = new URLSearchParams(window.location.search).get("q")?.trim() ?? "";
      const ai = loadAiConfig();
      setModel(ai?.model ?? null);
      let acct: AccountInfo | null = null;
      try {
        if (msalConfigured()) {
          const msal = await getMsal();
          await msal.handleRedirectPromise().catch(() => null);
          acct = msal.getActiveAccount() ?? msal.getAllAccounts()[0] ?? null;
        }
      } catch {
        acct = null;
      }
      if (!acct) {
        setInput(q);
        return setMode("sample");
      }
      const health = await runtimeHealth();
      if (!health) {
        setOffline(true);
        return setMode("sample");
      }
      setVoiceOff(
        ai?.mode !== "key"
          ? "Voice needs a Meta API key — switch to key mode in Settings (local AI can't transcribe)"
          : health.voice === false
            ? "Voice isn't available on your reader service (ffmpeg is missing)"
            : null,
      );
      setAccount(acct);
      setMode("live");
      if (q && !asked.current) {
        asked.current = true; // the home page's Ask bar sent a question: answer it straight away
        await ask(q, acct, []);
      }
    })();
  }, []);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (mode === "live" && account && !busy) void ask(input, account, turns);
  }

  const live = mode === "live";
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Ask</h1>
        <p className="mt-1 text-[15px] leading-7 text-muted">
          Ask your books in plain English. Numbers are calculated by code from your ledger; your AI only writes the
          words, and every answer shows the files it used.
          {live && (
            <>
              {" "}
              Answering with <strong className="text-ink">{model ?? "the reader's default AI"}</strong> ·{" "}
              <Link href="/settings" className="font-bold text-teal underline underline-offset-2">
                change
              </Link>
            </>
          )}
        </p>
      </div>

      {mode === "sample" && (
        <div className="flex flex-col gap-4">
          <p className="w-fit rounded-full bg-ink px-3 py-1 text-[12px] font-bold tracking-wide text-ground">
            SAMPLE — FICTIONAL COMPANY
          </p>
          {offline && (
            <p className="rounded-xl border border-warn-border bg-warn-bg p-3 text-[14px] leading-6 text-warn-ink">
              Your reader service at {RUNTIME_URL} isn&apos;t answering, so this is the sample conversation.
            </p>
          )}
          <Question text={sampleQuestion} />
          <AnswerCard answer={sampleAnswer} />
        </div>
      )}

      {live && (
        <div className="flex flex-col gap-4" aria-live="polite">
          {turns.length === 0 && (
            <p className="rounded-2xl bg-ground p-5 text-[15px] leading-7 text-muted">
              Try “Why is my VAT different from last quarter?”, “Who did I spend most with?” or “What&apos;s waiting
              for me to approve?”. Answers cover your current VAT quarter and the one before.
            </p>
          )}
          {turns.map((t, i) => (
            <div key={i} className="flex flex-col gap-3">
              <Question text={t.question} />
              {t.answer ? (
                <AnswerCard answer={t.answer} />
              ) : t.error ? (
                <p className="rounded-2xl border border-warn-border bg-warn-bg p-4 text-[14px] leading-6 text-warn-ink">
                  Couldn&apos;t get an answer. {t.error}
                </p>
              ) : (
                <p className="rounded-2xl border border-border bg-white p-4 text-[14px] text-muted">
                  Reading your books…
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      <div ref={end} />

      <form onSubmit={submit} className="flex items-center gap-2 rounded-2xl border border-border bg-white p-2 pl-4">
        <label htmlFor="ask-input" className="sr-only">
          Ask your books
        </label>
        <input
          id="ask-input"
          type="text"
          maxLength={500}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={!live || busy}
          placeholder={
            live
              ? "Ask your books — “how much VAT do I owe and why?”"
              : offline
                ? "Reader service not reachable"
                : "Sign in to ask your own books"
          }
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted disabled:opacity-60"
        />
        {live && (
          <MicButton
            disabled={busy || voiceOff !== null}
            reason={busy ? "Wait for the answer" : (voiceOff ?? undefined)}
            onRecorded={(audio) => {
              setVoiceNote(null);
              if (account) void askVoice(audio, account, turns);
            }}
            onError={setVoiceNote}
          />
        )}
        {live ? (
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="flex h-10 shrink-0 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50"
          >
            {busy ? "Asking…" : "Ask"}
          </button>
        ) : (
          <Link
            href={offline ? "/settings" : "/connect"}
            className="flex h-10 shrink-0 items-center rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
          >
            {offline ? "Settings" : "Sign in"}
          </Link>
        )}
      </form>
      {voiceNote && (
        <p role="status" className="-mt-4 px-2 text-[13px] text-warn-ink">
          {voiceNote}
        </p>
      )}
    </div>
  );
}
