"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import Explain from "@/components/Explain";
import PageHeader from "@/components/PageHeader";
import { EmptyState, LoadingSkeleton, ReaderErrorNote, RuntimeErrorNote } from "@/components/States";
import { todayIso } from "@/components/jobs/useAccount";
import { loadAiConfig, RUNTIME_URL } from "@/lib/ai-config";
import { deadlinesQuery, loadBusiness } from "@/lib/business";
import { getMsal, msalConfigured } from "@/lib/msal";
import { runtime, runtimeHealth, type RtAskAnswer, type RtAskTurn } from "@/lib/runtime";
import { sampleAnswer, sampleQuestion } from "@/lib/sample-ask";
import { pickedPeriod } from "@/lib/vat-period";
import ActionCard, { ClarifyCard, withPicked } from "./ActionCard";
import AnswerCard from "./AnswerCard";
import MicButton from "./MicButton";
import { FALLBACK_QUESTIONS, suggestedQuestions } from "./suggested";

interface Turn {
  question: string; // empty while a spoken question is being transcribed
  answer?: RtAskAnswer;
  error?: string;
  /** Seconds the answer took, timed around the ask call (the runtime sends no timing). */
  elapsedS?: number;
  /** From hold-to-talk: tapping the transcript puts it back in the box to edit. */
  voice?: boolean;
}

type Mode = "loading" | "sample" | "live";

function Question({ text, voice, onEdit }: { text: string; voice?: boolean; onEdit?: () => void }) {
  const bubble =
    "max-w-[min(32rem,85%)] rounded-2xl bg-teal px-4 py-3 text-left text-[15px] leading-6 text-white";
  return (
    <div className="flex justify-end">
      {text ? (
        voice && onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            title="Tap to edit and ask again"
            aria-label={`Your spoken question: ${text}. Tap to edit and ask again.`}
            className={`${bubble} hover:bg-teal-dark`}
          >
            {text}
          </button>
        ) : (
          <p className={bubble}>{text}</p>
        )
      ) : (
        <p className="rounded-2xl bg-teal/70 px-4 py-3 text-[15px] italic leading-6 text-white">Transcribing…</p>
      )}
    </div>
  );
}

/** The period picked on /vat, if any; otherwise null and the runtime uses the current VAT period. */
function askPeriod() {
  const p = pickedPeriod();
  return p ? { start: p.start, end: p.end } : null;
}

/** The last turns of this tab's conversation, kept in sessionStorage so a reload keeps the thread. */
const HISTORY_KEY = "accnomos.ask-history";
const MAX_TURNS = 6;

function loadTurns(): Turn[] {
  try {
    if (typeof window === "undefined") return [];
    const raw = window.sessionStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return (parsed as Turn[]).filter((t) => t && typeof t.question === "string" && (t.answer ?? t.error)).slice(-MAX_TURNS);
  } catch {
    return [];
  }
}

function keepTurns(turns: Turn[]): void {
  try {
    const keep = turns.filter((t) => t.question && (t.answer ?? t.error)).slice(-MAX_TURNS);
    window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(keep));
  } catch {
    /* storage unavailable — the thread lives for this page only */
  }
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
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const asked = useRef(false);

  function historyOf(before: Turn[]): RtAskTurn[] {
    return before
      .filter((t) => t.answer)
      .flatMap((t) => [
        { role: "user" as const, text: t.question },
        { role: "assistant" as const, text: t.answer!.answer_md },
      ]);
  }

  const ask = useCallback(async (question: string, acct: AccountInfo, before: Turn[]) => {
    const q = question.trim();
    if (!q) return;
    const history = historyOf(before);
    const started = performance.now();
    setTurns([...before, { question: q }]);
    setInput("");
    setBusy(true);
    try {
      const answer = await runtime.ask(acct, q, askPeriod(), history);
      setTurns([...before, { question: q, answer, elapsedS: (performance.now() - started) / 1000 }]);
    } catch (e) {
      setTurns([...before, { question: q, error: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
    }
  }, []);

  /** A spoken question: "Transcribing…" bubble, then the transcript replaces it and the answer renders as usual. */
  const askVoice = useCallback(async (audio: Blob, acct: AccountInfo, before: Turn[]) => {
    const started = performance.now();
    setTurns([...before, { question: "" }]);
    setBusy(true);
    try {
      const { transcript, ...answer } = await runtime.askVoice(acct, audio, askPeriod(), historyOf(before));
      setTurns([...before, { question: transcript, answer, elapsedS: (performance.now() - started) / 1000, voice: true }]);
    } catch (e) {
      setTurns([...before, { question: "(voice question)", error: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setBusy(false);
    }
  }, []);

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
      const stored = loadTurns();
      if (stored.length > 0) setTurns(stored);
      if (q && !asked.current) {
        asked.current = true; // the home page's Ask bar sent a question: answer it straight away
        await ask(q, acct, stored);
      } else if (stored.length === 0) {
        // An empty thread offers questions built from the dashboard payload — code, not a model.
        try {
          const vat = deadlinesQuery(loadBusiness());
          const dash = await runtime.dashboard(acct, `${vat ? `${vat}&` : ""}today=${todayIso()}`);
          setSuggestions(suggestedQuestions(dash));
        } catch {
          setSuggestions(FALLBACK_QUESTIONS);
        }
      }
    })();
  }, [ask]);

  useEffect(() => {
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    end.current?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "end" });
  }, [turns]);

  useEffect(() => {
    keepTurns(turns);
  }, [turns]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (mode === "live" && account && !busy) void ask(input, account, turns);
  }

  function clearConversation() {
    setTurns([]);
    try {
      window.sessionStorage.removeItem(HISTORY_KEY);
    } catch {
      /* nothing stored */
    }
  }

  const live = mode === "live";
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Ask"
        description="Ask your books in plain English. Numbers are calculated by code from your ledger; your AI only writes the words, and every answer shows the files it used."
        action={
          mode === "loading" ? null : (
            <div className="flex items-center gap-2">
              {live ? (
                <p className="text-[13px] font-semibold text-muted">
                  Answering with <strong className="text-ink">{model ?? "the reader's default AI"}</strong> ·{" "}
                  <Link href="/settings" className="whitespace-nowrap font-bold text-teal underline underline-offset-2">
                    change
                  </Link>
                </p>
              ) : (
                <p className="w-fit rounded-full bg-ink px-3 py-1 text-[12px] font-bold tracking-wide whitespace-nowrap text-ground">
                  SAMPLE — FICTIONAL COMPANY
                </p>
              )}
              <Explain title="Where answers come from">
                <p>
                  Numbers by code, words by model. Code gathers the facts from your ledger first;
                  your AI (Muse Glimmer on your machine, or Muse Spark with your key) only writes
                  the explanation around them. Every figure in the answer is checked against those
                  facts — an invented number is replaced by the quoted facts.
                </p>
                <p>
                  Each answer shows its key numbers and the files it used. “Worked out by code”
                  means the model was unavailable and code answered from the ledger alone.
                </p>
                <p>
                  Spoken questions are transcribed by Muse Voice Transcribe (key mode only) and
                  then go through the same grounded Ask. Audio is not kept.
                </p>
              </Explain>
            </div>
          )
        }
      />

      {mode === "sample" && (
        <div className="flex flex-col gap-4">
          {offline && (
            <ReaderErrorNote
              detail={`The app tried ${RUNTIME_URL}, so this is the sample conversation.`}
            />
          )}
          <Question text={sampleQuestion} />
          <AnswerCard answer={sampleAnswer} />
        </div>
      )}

      {live && turns.length > 0 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={clearConversation}
            className="shrink-0 whitespace-nowrap rounded-xl px-3 py-2 text-[14px] font-bold text-teal hover:bg-teal-tint"
          >
            New conversation
          </button>
        </div>
      )}

      {live && (
        <div className="flex min-w-0 flex-col gap-4 overflow-x-clip" role="log" aria-live="polite" aria-label="Conversation">
          {turns.length === 0 && (
            <>
              <EmptyState
                title="No questions yet"
                body="Your conversation history appears here — every answer is worked out by code from your ledger."
              />
              {suggestions && (
                <div className="flex flex-col gap-2">
                  <p className="text-[13px] font-bold text-muted">Try one of these</p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          if (account && !busy) void ask(s, account, turns);
                        }}
                        className="min-w-0 rounded-full border border-teal bg-white px-4 py-2.5 text-left text-[14px] font-bold text-teal hover:bg-teal-tint disabled:opacity-50"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          {turns.map((t, i) => (
            <div key={i} className="flex min-w-0 flex-col gap-3">
              <Question
                text={t.question}
                voice={t.voice}
                onEdit={
                  busy
                    ? undefined
                    : () => {
                        setInput(t.question);
                        inputRef.current?.focus();
                      }
                }
              />
              {t.answer?.proposed_action && account ? (
                <ActionCard
                  action={t.answer.proposed_action}
                  account={account}
                  onChange={() => {
                    setInput(t.question);
                    inputRef.current?.focus();
                  }}
                />
              ) : t.answer?.clarification ? (
                <ClarifyCard
                  clarification={t.answer.clarification}
                  onPick={(name) => {
                    if (account && !busy) void ask(withPicked(t.question, t.answer!.clarification!, name), account, turns);
                  }}
                />
              ) : t.answer ? (
                <AnswerCard answer={t.answer} account={account} elapsedS={t.elapsedS} />
              ) : t.error ? (
                <RuntimeErrorNote message={t.error} title="Couldn't get an answer" />
              ) : (
                <LoadingSkeleton lines={2} label="Reading your books…" />
              )}
            </div>
          ))}
        </div>
      )}
      <div ref={end} />

      <form
        onSubmit={submit}
        className="sticky bottom-16 z-30 flex items-center gap-2 rounded-2xl border border-border bg-white p-2 pl-4"
      >
        <label htmlFor="ask-input" className="sr-only">
          Ask your books
        </label>
        <input
          id="ask-input"
          ref={inputRef}
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
            className="flex h-10 shrink-0 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-50"
          >
            {busy ? "Asking…" : "Ask"}
          </button>
        ) : (
          <Link
            href={offline ? "/settings" : "/connect"}
            className="flex h-10 shrink-0 items-center whitespace-nowrap rounded-xl bg-teal px-5 text-[15px] font-bold text-white hover:bg-teal-dark"
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
