"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { RUNTIME_URL } from "@/lib/ai-config";
import { CONTACT_EMAIL, OPEN_CHAT_EVENT } from "@/lib/public-site";

/** Must match MESSAGE_MAX in services/runtime/app/public_chat.py. */
export const MESSAGE_MAX = 500;

const STARTERS = [
  "Where are my books stored?",
  "Can it file my VAT return to HMRC?",
  "Which Meta models does it use?",
];

type Cited = { id: string; title: string };
type Reply = { answer: string; sections: Cited[]; refused: boolean; reason: string; contact: string };
type Turn =
  | { role: "you"; text: string }
  | { role: "bot"; text: string; sections: Cited[]; refused: boolean; notes: boolean }
  | { role: "error"; text: string };

async function askRuntime(message: string): Promise<Reply> {
  const res = await fetch(`${RUNTIME_URL}/public/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (res.status === 429) {
    const wait = Number(res.headers.get("Retry-After") ?? "0");
    throw new Error(`That's a lot of questions in a minute. Try again${wait ? ` in ${wait} s` : " shortly"}.`);
  }
  if (!res.ok) throw new Error(`The chat isn't answering right now. Please email ${CONTACT_EMAIL}.`);
  return (await res.json()) as Reply;
}

/**
 * "Ask about Accnomos": a floating chat on the public pages (MarketingShell). It sends one question at a time to the
 * runtime's POST /public/chat, which answers only about Accnomos from the team's notes and refers anything else to
 * the contact address. Opened by its launcher or the menu (OPEN_CHAT_EVENT). A modal dialog: focus moves in, Tab stays
 * inside, Escape closes and focus returns to whatever opened it; new replies are announced politely.
 */
export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLOListElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const noteId = useId();
  const countId = useId();

  const show = useCallback((question?: string) => {
    opener.current = (document.activeElement as HTMLElement | null) ?? null;
    if (question) setDraft(question.slice(0, MESSAGE_MAX));
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    // Back to the launcher or menu item that opened it (the launcher if that is gone, e.g. a closed mobile menu).
    requestAnimationFrame(() => {
      const back = opener.current?.isConnected ? opener.current : document.getElementById("chat-launcher");
      back?.focus();
    });
  }, []);

  useEffect(() => {
    const onOpen = (e: Event) => show((e as CustomEvent<{ question?: string }>).detail?.question);
    window.addEventListener(OPEN_CHAT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_CHAT_EVENT, onOpen);
  }, [show]);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  useEffect(() => {
    log.current?.lastElementChild?.scrollIntoView({ block: "nearest" });
  }, [turns, busy]);

  // Focus trap and Escape.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
      return;
    }
    if (e.key !== "Tab" || !dialog.current) return;
    const focusable = [
      ...dialog.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      ),
    ].filter((el) => el.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const send = async (text: string) => {
    const message = text.trim().slice(0, MESSAGE_MAX);
    if (!message || busy) return;
    setTurns((t) => [...t, { role: "you", text: message }]);
    setDraft("");
    setBusy(true);
    try {
      const r = await askRuntime(message);
      setTurns((t) => [
        ...t,
        { role: "bot", text: r.answer, sections: r.sections, refused: r.refused, notes: r.reason === "notes" },
      ]);
    } catch (e) {
      const text =
        e instanceof TypeError
          ? `The chat isn't answering right now. Please email ${CONTACT_EMAIL}.`
          : (e as Error).message;
      setTurns((t) => [...t, { role: "error", text }]);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };

  return (
    <>
      <button
        id="chat-launcher"
        type="button"
        onClick={() => show()}
        aria-haspopup="dialog"
        aria-expanded={open}
        hidden={open}
        className="fixed bottom-4 right-4 z-40 flex h-14 w-14 items-center justify-center gap-2 rounded-full bg-ink text-sm font-bold text-ground shadow-frame hover:bg-teal-dark sm:bottom-6 sm:right-6 sm:h-auto sm:w-auto sm:px-4 sm:py-3"
      >
        <svg aria-hidden="true" width="22" height="22" viewBox="0 0 18 18" fill="none" className="sm:h-[18px] sm:w-[18px]">
          <path
            d="M3 4.5A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5v6a1.5 1.5 0 0 1-1.5 1.5H8l-3.5 3v-3h0A1.5 1.5 0 0 1 3 10.5v-6Z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
        {/* Icon only on phones, so it never covers the page's own buttons; the name is always there. */}
        <span className="max-sm:sr-only">Ask about Accnomos</span>
      </button>

      {open && (
        <div
          ref={dialog}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={noteId}
          onKeyDown={onKeyDown}
          className="chat-panel fixed inset-0 z-50 flex flex-col bg-white sm:inset-auto sm:bottom-6 sm:right-6 sm:h-[min(600px,calc(100vh-3rem))] sm:w-[400px] sm:rounded-2xl sm:border sm:border-border sm:shadow-frame"
        >
          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0">
              <h2 id={titleId} className="text-base font-extrabold">
                Ask about Accnomos
              </h2>
              <p id={noteId} className="mt-0.5 text-[13px] leading-snug text-muted">
                AI answers about Accnomos only, from the team&apos;s notes. For anything else contact the team at{" "}
                <a href={`mailto:${CONTACT_EMAIL}`} className="font-bold text-teal-dark underline underline-offset-2">
                  {CONTACT_EMAIL}
                </a>
                .
              </p>
            </div>
            <button
              type="button"
              onClick={close}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-ground hover:text-ink"
            >
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span className="sr-only">Close chat</span>
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {turns.length === 0 && (
              <div>
                <p className="text-sm text-muted">Try one of these, or type your own question.</p>
                <ul className="mt-3 flex flex-col items-start gap-2">
                  {STARTERS.map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        onClick={() => send(q)}
                        className="rounded-xl border border-border bg-ground px-3 py-2 text-left text-sm font-semibold hover:border-teal hover:bg-teal-tint"
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <ol ref={log} aria-live="polite" aria-label="Conversation" className="flex flex-col gap-3">
              {turns.map((t, i) => (
                <li key={i} className={t.role === "you" ? "self-end max-w-[85%]" : "max-w-[92%]"}>
                  {t.role === "you" ? (
                    <p className="rounded-2xl rounded-br-md bg-teal px-3.5 py-2.5 text-sm text-white">
                      <span className="sr-only">You: </span>
                      {t.text}
                    </p>
                  ) : t.role === "bot" ? (
                    <div
                      className={`rounded-2xl rounded-bl-md px-3.5 py-2.5 text-sm leading-relaxed ${
                        t.refused ? "border border-warn-border bg-warn-bg text-warn-ink" : "bg-ground text-ink"
                      }`}
                    >
                      <span className="sr-only">Accnomos assistant: </span>
                      <p>{t.text}</p>
                      {t.sections.length > 0 && (
                        <p className="mt-2 text-[12px] text-muted">
                          {t.notes ? "Quoted from" : "Based on"} our notes: {t.sections.map((s) => s.title).join("; ")}
                        </p>
                      )}
                    </div>
                  ) : (
                    <p role="alert" className="rounded-2xl border border-warn-border bg-warn-bg px-3.5 py-2.5 text-sm text-warn-ink">
                      {t.text}
                    </p>
                  )}
                </li>
              ))}
              {busy && (
                <li className="max-w-[92%]">
                  <p className="rounded-2xl rounded-bl-md bg-ground px-3.5 py-2.5 text-sm text-muted">
                    Looking it up<span className="chat-dots" aria-hidden="true" />
                  </p>
                </li>
              )}
            </ol>
          </div>

          <form
            className="border-t border-border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
          >
            <label htmlFor="chat-input" className="sr-only">
              Your question about Accnomos
            </label>
            <div className="flex items-end gap-2">
              <textarea
                id="chat-input"
                ref={input}
                value={draft}
                rows={2}
                maxLength={MESSAGE_MAX}
                aria-describedby={countId}
                placeholder="Ask about features, privacy, VAT…"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(draft);
                  }
                }}
                className="min-h-[44px] flex-1 resize-none rounded-xl border border-border bg-white px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy || !draft.trim()}
                title={busy ? "Waiting for the answer" : !draft.trim() ? "Type a question first" : undefined}
                className="h-11 shrink-0 rounded-xl bg-teal px-4 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-50"
              >
                Send
              </button>
            </div>
            <p id={countId} className="mt-1 text-right text-[11px] text-muted">
              {draft.length} / {MESSAGE_MAX}
            </p>
          </form>
        </div>
      )}
    </>
  );
}
