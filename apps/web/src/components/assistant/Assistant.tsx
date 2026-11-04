"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { usePathname } from "next/navigation";
import type { AccountInfo } from "@azure/msal-browser";
import { useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import ActionCard, { ClarifyCard, withPicked } from "@/components/ask/ActionCard";
import AnswerCard from "@/components/ask/AnswerCard";
import { askStream, runtime, type RtActionResult, type RtAskAnswer, type RtAskTurn, type RtProposedAction } from "@/lib/runtime";
import { ASK_AGAIN, cardReadBack, hearReply, inWords, LEFT_FOR_TAP, needsTap } from "@/lib/voiceApproval";
import { pickedPeriod } from "@/lib/vat-period";
import { useHousehold } from "@/lib/profiles";
import {
  isStopPhrase,
  MAX_EMPTY_TURNS,
  speakable,
  starterPrompts,
  STATE_LABEL,
  trimForSpeech,
  type HandsFreeState,
} from "@/lib/handsfree";
import { MicError, recordTurn, speak } from "./recordTurn";

interface Turn {
  question: string; // empty while a spoken question is being heard
  answer?: RtAskAnswer;
  draft?: RtAskAnswer;
  error?: string;
  voice?: boolean;
  heardBy?: string;
  at?: number;
}

const KEY = "accnomos.assistant-history";
const MAX_TURNS = 6;

function loadTurns(): Turn[] {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Turn[]).filter((t) => t?.question && (t.answer ?? t.error)).slice(-MAX_TURNS) : [];
  } catch {
    return [];
  }
}

function historyOf(turns: Turn[]): RtAskTurn[] {
  return turns
    .filter((t) => t.answer && t.question)
    .flatMap((t) => [
      { role: "user" as const, text: t.question },
      { role: "assistant" as const, text: t.answer!.answer_md },
    ]);
}

function askPeriod() {
  const p = pickedPeriod();
  return p ? { start: p.start, end: p.end } : null;
}

const errorText = (e: unknown) => {
  const m = e instanceof Error ? e.message : String(e);
  return /"detail":\s*"([^"]+)"/.exec(m)?.[1] ?? m;
};

/** The two-tone mark: a speech bubble with a microphone inside. */
function TalkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 5h16v11H9l-5 4z" strokeLinejoin="round" />
      <rect x="10.5" y="7" width="3" height="5" rx="1.5" />
      <path d="M9 11a3 3 0 0 0 6 0" strokeLinecap="round" />
    </svg>
  );
}

/**
 * "Talk to Accnomos": a button on every signed-in and demo page that opens a conversation drawer. Type, tap the mic
 * for one spoken question, or turn on Hands-free (lib/handsfree.ts): it listens, sends what it heard to Ask (Muse
 * Voice Transcribe, then the same checked answer as the Ask page), reads the answer aloud and listens again. A card
 * that changes something is shown and read back in words, then "Shall I go ahead? Say yes or no.": a clear yes sends
 * the same signed approval as the Approve button, marked as spoken (lib/voiceApproval.ts); no, silence or two unclear
 * replies leave the card for tapping. Cards that send or move money (`tap_only`) always need the tap.
 */
export default function Assistant() {
  const path = usePathname() ?? "/";
  const account = useAccount();
  const household = useHousehold();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [hands, setHands] = useState<HandsFreeState>("off");
  const [level, setLevel] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  /** What the microphone is doing: the hands-free loop, one spoken question, or nothing. */
  const [run, setRun] = useState<"none" | "loop" | "once">("none");
  const turnsRef = useRef<Turn[]>([]);
  const loop = useRef<AbortController | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  /** Each card on screen that can still be approved, by action id: approves it as the button does, but spoken. */
  const voiceApprovers = useRef(new Map<string, (heard: string) => Promise<RtActionResult | null>>());
  const readyHooks = useRef(new Map<string, (fn: ((heard: string) => Promise<RtActionResult | null>) | null) => void>());
  const voiceReady = useCallback((id: string) => {
    let hook = readyHooks.current.get(id);
    if (!hook) {
      hook = (fn) => {
        if (fn) voiceApprovers.current.set(id, fn);
        else voiceApprovers.current.delete(id);
      };
      readyHooks.current.set(id, hook);
    }
    return hook;
  }, []);

  const put = useCallback((next: Turn[]) => {
    turnsRef.current = next;
    setTurns(next);
    try {
      const keep = next.filter((t) => t.question && (t.answer ?? t.error)).slice(-MAX_TURNS);
      window.sessionStorage.setItem(KEY, JSON.stringify(keep));
    } catch {
      /* storage unavailable: the conversation lives for this page */
    }
  }, []);

  useEffect(() => {
    const stored = loadTurns();
    turnsRef.current = stored;
    queueMicrotask(() => setTurns(stored));
  }, []);

  const stopHands = useCallback(() => {
    loop.current?.abort();
    loop.current = null;
    setHands("off");
    setRun("none");
    setLevel(0);
  }, []);

  const close = useCallback(() => {
    stopHands();
    setOpen(false);
    queueMicrotask(() => opener.current?.focus());
  }, [stopHands]);

  useEffect(() => () => loop.current?.abort(), []);

  useEffect(() => {
    if (!open) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    end.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "end" });
  }, [turns, open]);

  useEffect(() => {
    if (open) queueMicrotask(() => inputRef.current?.focus());
  }, [open]);

  /** A typed question: streamed like the Ask page, with the plain call as the fallback. */
  const ask = useCallback(
    async (question: string, acct: AccountInfo) => {
      const q = question.trim();
      if (!q) return;
      const before = turnsRef.current;
      put([...before, { question: q }]);
      setInput("");
      setBusy(true);
      try {
        let draft: RtAskAnswer | null = null;
        const show = (d: RtAskAnswer) => {
          draft = d;
          put([...before, { question: q, draft: d }]);
        };
        let answer: RtAskAnswer;
        try {
          answer = await askStream(acct, q, askPeriod(), historyOf(before), {
            onStart: (p) => show({ ...p, answer_md: "", confidence: "high", fallback_reason: null }),
            onToken: (text) => {
              if (draft) show({ ...draft, answer_md: draft.answer_md + text });
            },
          });
        } catch {
          answer = await runtime.ask(acct, q, askPeriod(), historyOf(before));
        }
        put([...before, { question: q, answer, at: Date.now() }]);
      } catch (e) {
        put([...before, { question: q, error: errorText(e) }]);
      } finally {
        setBusy(false);
      }
    },
    [put],
  );

  /** A spoken question: heard and answered in one call (POST /books/ask/voice). */
  const askSpoken = useCallback(
    async (audio: Blob, acct: AccountInfo): Promise<{ transcript: string; answer: RtAskAnswer } | null> => {
      const before = turnsRef.current;
      put([...before, { question: "", voice: true }]);
      try {
        const { transcript, transcribed_by, ...answer } = await runtime.askVoice(acct, audio, askPeriod(), historyOf(before));
        if (isStopPhrase(transcript)) {
          put(before); // "stop" ends the conversation; it is not a question
          return { transcript, answer };
        }
        put([...before, { question: transcript, answer, voice: true, heardBy: transcribed_by?.label, at: Date.now() }]);
        return { transcript, answer };
      } catch (e) {
        put([...before, { question: "(spoken question)", voice: true, error: errorText(e) }]);
        return null;
      }
    },
    [put],
  );

  /**
   * Verbal approval: read the card back, ask "Shall I go ahead?", and approve on a clear yes. "done" when approved;
   * "left" when the card stays on screen (no, silence, unclear twice, a card that needs a tap, or it failed).
   */
  const askToApprove = useCallback(
    async (acct: AccountInfo, action: RtProposedAction, signal: AbortSignal): Promise<"done" | "left"> => {
      setHands("speaking");
      await speak(cardReadBack(action), signal);
      if (signal.aborted || needsTap(action)) return "left";
      for (let attempt = 0; attempt < 2; attempt++) {
        setHands("listening");
        const audio = await recordTurn(setLevel, signal);
        setLevel(0);
        if (signal.aborted) return "left";
        let heard = "";
        if (audio) {
          setHands("thinking");
          try {
            heard = (await runtime.transcribe(acct, audio)).transcript;
          } catch {
            heard = ""; // not heard: treated as no, and the card stays
          }
        }
        const reply = hearReply(heard);
        if (reply === "yes") {
          const approve = voiceApprovers.current.get(action.id);
          setHands("speaking");
          if (!approve) {
            await speak("That card can't be approved any more. Nothing has changed.", signal);
            return "left";
          }
          setHands("thinking");
          const result = await approve(heard);
          setHands("speaking");
          await speak(result ? trimForSpeech(inWords(speakable(result.summary_md))) : "That didn't go through. The reason is on screen.", signal);
          return result ? "done" : "left";
        }
        setHands("speaking");
        if (reply === "no") {
          await speak(LEFT_FOR_TAP, signal);
          return "left";
        }
        if (attempt === 0) await speak(ASK_AGAIN, signal);
      }
      await speak(LEFT_FOR_TAP, signal);
      return "left";
    },
    [],
  );

  /** Hands-free: listen → answer → speak → listen, until Stop, a stop phrase, two empty turns or a card to approve. */
  const startHands = useCallback(async () => {
    if (!account || loop.current) return;
    const ctrl = new AbortController();
    loop.current = ctrl;
    setRun("loop");
    setNote(null);
    let empty = 0;
    try {
      while (!ctrl.signal.aborted) {
        setHands("listening");
        let audio: Blob | null;
        try {
          audio = await recordTurn(setLevel, ctrl.signal);
        } catch (e) {
          setNote(e instanceof MicError ? e.message : errorText(e));
          break;
        }
        if (ctrl.signal.aborted) break;
        if (!audio) {
          empty += 1;
          if (empty >= MAX_EMPTY_TURNS) {
            setNote("Hands-free stopped: I didn't hear anything. Tap Hands-free to start again.");
            break;
          }
          continue;
        }
        empty = 0;
        setHands("thinking");
        setBusy(true);
        const res = await askSpoken(audio, account);
        setBusy(false);
        if (ctrl.signal.aborted || !res) break;
        if (isStopPhrase(res.transcript)) {
          await speak("Okay.", ctrl.signal);
          break;
        }
        setHands("speaking");
        if (res.answer.proposed_action) {
          let outcome: "done" | "left";
          try {
            outcome = await askToApprove(account, res.answer.proposed_action, ctrl.signal);
          } catch (e) {
            setNote(e instanceof MicError ? e.message : errorText(e));
            break;
          }
          if (outcome === "done") continue;
          if (!ctrl.signal.aborted) setNote("Hands-free paused: the card is on screen to tap.");
          break;
        }
        if (res.answer.clarification) {
          await speak(`${trimForSpeech(speakable(res.answer.clarification.question_md))} Pick one on screen.`, ctrl.signal);
          setNote("Hands-free paused: pick an answer on screen.");
          break;
        }
        await speak(trimForSpeech(speakable(res.answer.answer_md)), ctrl.signal);
      }
    } finally {
      setBusy(false);
      if (loop.current === ctrl) {
        loop.current = null;
        setRun("none");
      }
      setHands("off");
      setLevel(0);
    }
  }, [account, askSpoken, askToApprove]);

  /** One spoken question without the loop. */
  const micOnce = useCallback(async () => {
    if (!account || loop.current || busy) return;
    const ctrl = new AbortController();
    loop.current = ctrl;
    setRun("once");
    setNote(null);
    try {
      setHands("listening");
      const audio = await recordTurn(setLevel, ctrl.signal);
      if (!audio) {
        if (!ctrl.signal.aborted) setNote("I didn't hear anything. Try again, or type your question.");
        return;
      }
      setHands("thinking");
      setBusy(true);
      const res = await askSpoken(audio, account);
      setBusy(false);
      if (res?.answer.proposed_action && !ctrl.signal.aborted) await askToApprove(account, res.answer.proposed_action, ctrl.signal);
    } catch (e) {
      setNote(e instanceof MicError ? e.message : errorText(e));
    } finally {
      setBusy(false);
      if (loop.current === ctrl) {
        loop.current = null;
        setRun("none");
      }
      setHands("off");
      setLevel(0);
    }
  }, [account, askSpoken, askToApprove, busy]);

  // Keyboard: Esc closes, Tab stays inside the drawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "Tab" && panel.current) {
        const items = [...panel.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input,textarea,select,[tabindex]:not([tabindex='-1'])")];
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!account || path === "/ask" || path.startsWith("/accountant")) return null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (account && !busy) void ask(input, account);
  }

  const listening = hands === "listening";
  const handsOn = run === "loop";
  const onceOn = run === "once";

  return (
    <>
      {!open && (
        <button
          ref={opener}
          type="button"
          data-assistant-open=""
          onClick={() => setOpen(true)}
          aria-label="Talk to Accnomos"
          title="Talk to Accnomos — ask by voice or chat"
          className="fixed bottom-[calc(5.5rem+env(safe-area-inset-bottom))] right-4 z-40 flex h-14 items-center gap-2 rounded-full bg-teal px-4 text-[15px] font-bold text-white shadow-lg hover:bg-teal-dark min-[900px]:bottom-6 min-[900px]:right-6 print:hidden"
        >
          <TalkIcon />
          <span className="hidden sm:inline">Talk to Accnomos</span>
        </button>
      )}
      {open && (
        <div className="fixed inset-0 z-50 print:hidden" data-assistant="">
          <div className="absolute inset-0 bg-ink/30" aria-hidden="true" onClick={close} />
          <div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby="assistant-title"
            className="absolute inset-y-0 right-0 flex w-full flex-col bg-ground shadow-xl sm:max-w-md"
          >
            <header className="flex items-center gap-3 border-b border-border bg-white px-4 py-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-teal text-white">
                <TalkIcon />
              </span>
              <div className="min-w-0 flex-1">
                <h2 id="assistant-title" className="text-[16px] font-bold text-ink">
                  Talk to Accnomos
                </h2>
                <p className="text-[13px] text-muted">Answers from your books; every figure checked by code.</p>
              </div>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="flex h-11 w-11 items-center justify-center rounded-xl text-muted hover:bg-ground"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                </svg>
              </button>
            </header>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
              {turns.length === 0 && (
                <div className="space-y-3">
                  <p className="text-[15px] leading-6 text-ink">
                    Ask about your {household ? "money" : "books"} by typing, or turn on <strong>Hands-free</strong> and just talk.
                  </p>
                  <ul className="flex flex-wrap gap-2">
                    {starterPrompts(household).map((p) => (
                      <li key={p}>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => account && void ask(p, account)}
                          className="min-h-11 rounded-xl border border-border bg-white px-3 py-2 text-left text-[14px] text-ink hover:border-teal disabled:opacity-50"
                        >
                          {p}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {turns.map((t, i) => (
                <div key={i} className="space-y-2">
                  <div className="flex flex-col items-end gap-1">
                    <p className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-6 text-white ${t.question ? "bg-teal" : "bg-teal/70 italic"}`}>
                      {t.question || "Listening to what you said…"}
                    </p>
                    {t.question && t.voice && t.heardBy && <p className="text-[12px] text-muted">Transcribed by {t.heardBy}</p>}
                  </div>
                  {t.answer?.proposed_action ? (
                    <ActionCard
                      action={t.answer.proposed_action}
                      account={account}
                      receivedAt={t.at}
                      spoken={t.voice ? t.question : undefined}
                      onVoiceReady={voiceReady(t.answer.proposed_action.id)}
                      onChange={() => {
                        setInput(t.question);
                        inputRef.current?.focus();
                      }}
                    />
                  ) : t.answer?.clarification ? (
                    <ClarifyCard
                      clarification={t.answer.clarification}
                      account={account}
                      onPick={(name) => {
                        if (!busy) void ask(withPicked(t.question, t.answer!.clarification!, name), account);
                      }}
                    />
                  ) : t.answer ? (
                    <AnswerCard answer={t.answer} account={account} />
                  ) : t.draft ? (
                    <AnswerCard answer={t.draft} account={account} pending />
                  ) : t.error ? (
                    <RuntimeErrorNote message={t.error} title="Couldn't get an answer" />
                  ) : (
                    <p className="text-[14px] text-muted">Reading your books…</p>
                  )}
                </div>
              ))}
              <div ref={end} />
            </div>

            <footer className="space-y-3 border-t border-border bg-white px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  data-handsfree=""
                  aria-pressed={handsOn}
                  disabled={!handsOn && busy}
                  onClick={() => (handsOn ? stopHands() : void startHands())}
                  className={`flex min-h-11 items-center gap-2 rounded-xl border px-3 text-[14px] font-bold ${
                    handsOn ? "border-teal bg-teal text-white" : "border-border bg-white text-teal-dark hover:border-teal"
                  } disabled:opacity-50`}
                >
                  {handsOn ? "Stop hands-free" : "Hands-free"}
                </button>
                <p className="min-w-0 flex-1 text-[14px] text-muted" role="status" data-handsfree-state={hands}>
                  {hands === "off" ? (note ?? "Type, tap the mic, or go hands-free.") : STATE_LABEL[hands]}
                </p>
                {listening && (
                  <span className="flex h-6 w-16 items-center overflow-hidden rounded-full bg-ground" aria-hidden="true">
                    <span className="h-full bg-teal transition-[width] duration-100" style={{ width: `${Math.round(level * 100)}%` }} />
                  </span>
                )}
              </div>
              <form onSubmit={submit} className="flex items-center gap-2">
                <label htmlFor="assistant-input" className="sr-only">
                  Your question
                </label>
                <input
                  ref={inputRef}
                  id="assistant-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={household ? "Ask about your money…" : "Ask about your books…"}
                  maxLength={500}
                  className="min-h-11 min-w-0 flex-1 rounded-xl border border-border bg-white px-3 text-[16px] text-ink outline-none focus:border-teal"
                />
                <button
                  type="button"
                  onClick={() => (onceOn ? stopHands() : void micOnce())}
                  disabled={handsOn || (busy && !onceOn)}
                  aria-label={onceOn ? "Stop listening" : "Ask by voice"}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-white text-ink hover:border-teal disabled:opacity-40"
                >
                  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <rect x="9" y="3" width="6" height="12" rx="3" />
                    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
                  </svg>
                </button>
                <button
                  type="submit"
                  disabled={busy || !input.trim()}
                  className="min-h-11 shrink-0 rounded-xl bg-teal px-4 text-[15px] font-bold text-white hover:bg-teal-dark disabled:opacity-40"
                >
                  Send
                </button>
              </form>
            </footer>
          </div>
        </div>
      )}
    </>
  );
}
