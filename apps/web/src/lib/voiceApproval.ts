/**
 * Verbal approval in the assistant (hands-free and push-to-talk). After a card is shown the assistant reads it back
 * in words and asks "Shall I go ahead? Say yes or no." A clear yes sends the same signed POST /actions/approve the
 * Approve button sends, marked `via: "voice"` with what was heard (the runtime checks the words again and audits
 * them). No, cancel or silence: nothing happens and the card stays for tapping. Unclear: ask once more, then leave it.
 * Cards marked `tap_only` by the runtime (app/actions.py `needs_tap`: anything that sends or moves money) never take a
 * spoken yes; the runtime refuses them too.
 */
import { penceInWords, readBack } from "@/lib/readback";
import { speakable, trimForSpeech } from "@/lib/handsfree";
import type { RtProposedAction } from "@/lib/runtime";

/** Mirrors app/actions.py YES_WORDS: the whole reply must be a yes, optionally with "please" or "thanks". */
const YES =
  /^\s*(?:yes|yeah|yep|yup|ok(?:ay)?|sure|approve(?:d)?|go ahead|do it|confirm(?:ed)?|please do|that'?s right)\b[\s.!,]*(?:please|thanks|thank you)?[\s.!]*$/i;
const NO = /^\s*(?:no|nope|nah|cancel|stop|don'?t|do not|leave it|not now|never mind|reject|wait)\b/i;

export type Reply = "yes" | "no" | "unclear";

/** How a spoken reply to "Shall I go ahead?" is taken. Empty (silence) is a no. */
export function hearReply(text: string | null | undefined): Reply {
  const t = (text ?? "").trim();
  if (!t || NO.test(t)) return "no";
  return YES.test(t) ? "yes" : "unclear";
}

export function needsTap(action: Pick<RtProposedAction, "tap_only">): boolean {
  return action.tap_only === true;
}

function hour(h: number, m: number): string {
  const ap = h < 12 ? "am" : "pm";
  const h12 = h % 12 || 12;
  if (h === 12 && m === 0) return "noon";
  return m ? `${h12} ${String(m).padStart(2, "0")} ${ap}` : `${h12} ${ap}`;
}

/** Money and clock times as words for the device voice: "£40.00" → "forty pounds", "15:00–16:00" → "3 pm to 4 pm". */
export function inWords(text: string): string {
  return text
    .replace(/£\s?(\d[\d,]*)(?:\.(\d{2}))?/g, (_, p: string, d?: string) => penceInWords(Number(p.replace(/,/g, "")) * 100 + Number(d ?? 0)))
    .replace(/\b([01]?\d|2[0-3]):([0-5]\d)\s*[–-]\s*([01]?\d|2[0-3]):([0-5]\d)\b/g, (_, a, b, c, d) => `${hour(+a, +b)} to ${hour(+c, +d)}`)
    .replace(/\b([01]?\d|2[0-3]):([0-5]\d)\b/g, (_, a, b) => hour(+a, +b));
}

/** What the assistant says after showing a card: the card in words, then the question (or why it needs a tap). */
export function cardReadBack(action: RtProposedAction): string {
  const said = inWords(speakable(action.summary_md));
  const figures = readBack(action.kind, action.preview as Record<string, unknown>)
    .map((f) => `${f.label}: ${f.words}.`)
    .join(" ");
  const body = trimForSpeech([said, figures].filter(Boolean).join(" "));
  if (needsTap(action)) return `${body} This one sends or moves money, so it needs you to tap Approve on screen. I won't take a spoken yes for it.`;
  const clash = Array.isArray(action.preview.conflicts) && action.preview.conflicts.length > 0;
  return `${body} ${clash ? "Add it anyway?" : "Shall I go ahead?"} Say yes or no.`;
}

export const ASK_AGAIN = "Sorry, I didn't catch that. Say yes to go ahead, or no to leave it.";
export const LEFT_FOR_TAP = "Okay, I've left it on screen. Nothing has changed; you can tap Approve or Reject.";
