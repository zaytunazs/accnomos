/**
 * The hands-free conversation's rules, kept apart from the UI so they can be read and tested on their own
 * (components/assistant/Assistant.tsx uses them).
 *
 * One turn: listen → (the recording is sent to POST /books/ask/voice: Muse Voice Transcribe hears it, the Ask
 * pipeline answers with every figure checked) → speak the answer → listen again. The loop ends when the user taps
 * Stop, says a stop phrase ("stop", "that's all", …) or two turns in a row hear nothing. A card is read back and the
 * user asked "Shall I go ahead?" (lib/voiceApproval.ts): a clear yes approves it as the button does and the loop goes
 * on; anything else, or a card that sends or moves money, leaves it on screen for a tap and pauses the loop.
 */

export type HandsFreeState = "off" | "listening" | "thinking" | "speaking";

export const STATE_LABEL: Record<HandsFreeState, string> = {
  off: "Hands-free is off",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

/** Level (0–1, the meter's scale) above which the microphone counts as speech. */
export const SPEECH_LEVEL = 0.12;
/** Quiet after speech that ends a question. */
export const SILENCE_MS = 1200;
/** A question, not a memo. */
export const MAX_TURN_MS = 30_000;
/** Nothing said at all for this long: an empty turn. */
export const NO_SPEECH_MS = 8000;
/** Empty turns in a row that end hands-free. */
export const MAX_EMPTY_TURNS = 2;

const STOP = /^\s*(?:ok(?:ay)?[,\s]+)?(?:stop(?: listening)?|that'?s all|that is all|thanks?,? that'?s all|no more|goodbye|bye|cancel|end(?: the)? conversation|nothing else)[.!\s]*$/i;

/** "Stop", "that's all", "goodbye"… as the whole utterance (not "stop paying Acme"). */
export function isStopPhrase(text: string): boolean {
  return STOP.test(text.trim());
}

/** What the recorder decides at each level reading. */
export type Tick = "continue" | "end" | "empty";

/**
 * The end-of-speech rule, from the time since recording started, whether speech has been heard, and when the level
 * last crossed SPEECH_LEVEL: quiet for SILENCE_MS after speech ends the question; no speech for NO_SPEECH_MS is an
 * empty turn; MAX_TURN_MS ends it whatever.
 */
export function decide(nowMs: number, startedMs: number, heardMs: number | null): Tick {
  if (nowMs - startedMs >= MAX_TURN_MS) return heardMs === null ? "empty" : "end";
  if (heardMs === null) return nowMs - startedMs >= NO_SPEECH_MS ? "empty" : "continue";
  return nowMs - heardMs >= SILENCE_MS ? "end" : "continue";
}

/** Markdown answer → plain sentences for speech: no symbols read out, links and emphasis dropped. */
export function speakable(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`#>|]+/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\.(\s*\.)+/g, ".")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Speech settings: at most this many characters are read (the rest stays on screen). */
export const SPEAK_MAX = 600;

export function trimForSpeech(text: string): string {
  if (text.length <= SPEAK_MAX) return text;
  const cut = text.lastIndexOf(". ", SPEAK_MAX);
  return `${text.slice(0, cut > 200 ? cut + 1 : SPEAK_MAX)} The rest is on screen.`;
}

/** Starter prompts: a household never gets VAT or turnover. */
export function starterPrompts(household: boolean): string[] {
  return household
    ? [
        "Where did my money go this month?",
        "How much did I spend on eating out this month?",
        "Which budgets am I over?",
        "What bills are coming up?",
      ]
    : [
        "How much VAT do I owe and why?",
        "Who owes me the most?",
        "What needs my attention today?",
        "How are sales this month compared with last?",
      ];
}
