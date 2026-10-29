/**
 * Reads the shot tables out of the video scripts (docs/video/JUDGES_VIDEO.md, docs/video/CLIPS.md, or the older
 * docs/submission/VIDEO_SCRIPT.md). Any Markdown table whose header has a time or duration column and a shot,
 * caption or voice-over column is a list of shots; the nearest heading above it names the sequence.
 *
 * Recognised columns (case-insensitive, first match wins):
 *   id      "id", "shot id", "#", "no"
 *   time    "time", "timing", "timecode"  (a range: 0:07–0:17)   or  "duration", "length", "secs" (7 s, 0:07, 7)
 *   what    "shot", "screen", "visual", "what we see", "on screen", "action"
 *   caption "caption", "on-screen caption", "on-screen text", "burned caption", "lower third"
 *   vo      "voice-over", "voiceover", "vo", "narration", "script"
 *   flow    "flow", "capture"  (a flow name from tools/video/flows.ts; else the flow is chosen from `what`)
 */
import { readFileSync } from "node:fs";

export interface ScriptShot {
  /** Stable id, used for file names: docs/video/raw/<id>.webm and the voice-over <id>.wav. */
  id: string;
  sequence: string;
  index: number;
  duration: number;
  what: string;
  caption: string;
  vo: string;
  flow?: string;
}

export interface Sequence {
  id: string;
  title: string;
  shots: ScriptShot[];
}

const COLS: Record<keyof Pick<ScriptShot, "id" | "what" | "caption" | "vo" | "flow">, string[]> & {
  time: string[];
  duration: string[];
} = {
  id: ["shot id", "id", "#", "no", "no."],
  time: ["time", "timing", "timecode", "start–end", "start-end"],
  duration: ["duration", "length", "secs", "seconds", "dur"],
  what: ["shot", "screen", "visual", "what we see", "on screen", "action", "scene", "what's on screen"],
  caption: ["on-screen caption", "caption", "on-screen text", "burned caption", "lower third", "captions", "text on screen"],
  vo: ["voice-over", "voiceover", "voice over", "vo", "narration", "script", "vo text"],
  flow: ["flow", "capture"],
};

export function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[`*_]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

/** Markdown cell text: no emphasis, code ticks or surrounding quotes. */
function clean(s: string): string {
  return s
    .replace(/\\\|/g, "|")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/\*\*|__/g, "")
    // Stage directions in a caption cell ("(add `sped up` if the wait is cut)", "(if filmed in the browser: …)").
    .replace(/\s*\((?:if|add|or)\b[^)]*\)/gi, "")
    .replace(/`/g, "")
    .trim()
    .replace(/^["“]|["”]$/g, "")
    .trim();
}

function seconds(t: string): number {
  const m = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(t.trim());
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  const n = /(\d+(?:\.\d+)?)/.exec(t);
  return n ? Number(n[1]) : NaN;
}

/** "0:07–0:17" → 10; "7 s" → 7; "0:07" (a length) → 7. */
export function parseDuration(cell: string, isRange: boolean): number {
  const c = clean(cell);
  const range = /(\d+:\d{1,2}(?:\.\d+)?|\d+(?:\.\d+)?\s*s?)\s*[–—-]\s*(\d+:\d{1,2}(?:\.\d+)?|\d+(?:\.\d+)?\s*s?)/.exec(c);
  if (range) return Math.round((seconds(range[2]!) - seconds(range[1]!)) * 10) / 10;
  if (isRange) return NaN;
  return seconds(c);
}

function splitRow(line: string): string[] {
  const body = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return body.split(/(?<!\\)\|/).map((c) => c.trim());
}

function findCol(header: string[], names: string[]): number {
  const h = header.map((x) => clean(x).toLowerCase());
  for (const n of names) {
    const i = h.indexOf(n);
    if (i >= 0) return i;
  }
  for (const n of names) {
    if (n.length < 3) continue;
    const i = h.findIndex((x) => x.startsWith(n));
    if (i >= 0) return i;
  }
  return -1;
}

export function parseScript(file: string, defaultSequence: string): Sequence[] {
  const lines = readFileSync(file, "utf8").split(/\r?\n/);
  const seqs: Sequence[] = [];
  let heading = defaultSequence;
  let headingFlow: string | undefined;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const h = /^#{1,4}\s+(.*)$/.exec(line);
    if (h) {
      heading = clean(h[1]!);
      headingFlow = undefined;
      continue;
    }
    // An explicit sequence id under a heading: "id: clip-review" or "<!-- id: clip-review -->".
    const idLine = /^(?:<!--\s*)?(?:clip|sequence)?\s*id:\s*([a-z0-9-]+)/i.exec(line.trim());
    if (idLine) headingFlow = idLine[1];
    if (!line.trim().startsWith("|") || !lines[i + 1]?.trim().match(/^\|?\s*:?-{3,}/)) continue;
    const header = splitRow(line);
    const col = {
      id: findCol(header, COLS.id),
      time: findCol(header, COLS.time),
      duration: findCol(header, COLS.duration),
      what: findCol(header, COLS.what),
      caption: findCol(header, COLS.caption),
      vo: findCol(header, COLS.vo),
      flow: findCol(header, COLS.flow),
    };
    i += 2;
    const rows: string[][] = [];
    for (; i < lines.length && lines[i]!.trim().startsWith("|"); i++) rows.push(splitRow(lines[i]!));
    i--;
    if (col.time < 0 && col.duration < 0) continue;
    if (col.what < 0 && col.caption < 0 && col.vo < 0) continue;
    const seqId = headingFlow ?? (seqs.length === 0 && heading === defaultSequence ? defaultSequence : slug(heading) || defaultSequence);
    let seq = seqs.find((s) => s.id === seqId);
    if (!seq) {
      seq = { id: seqId, title: heading, shots: [] };
      seqs.push(seq);
    }
    for (const r of rows) {
      const cell = (k: number) => (k >= 0 ? clean(r[k] ?? "") : "");
      const dur = col.duration >= 0 ? parseDuration(r[col.duration] ?? "", false) : parseDuration(r[col.time] ?? "", true);
      if (!Number.isFinite(dur) || dur <= 0) continue;
      const index = seq.shots.length + 1;
      const rawId = cell(col.id);
      const id = /^[a-z][a-z0-9-]*$/i.test(rawId) && !/^\d+$/.test(rawId) ? rawId.toLowerCase() : `${seq.id}-${String(/^\d+$/.test(rawId) ? Number(rawId) : index).padStart(2, "0")}`;
      seq.shots.push({
        id,
        sequence: seq.id,
        index,
        duration: dur,
        what: cell(col.what),
        caption: cell(col.caption),
        vo: cell(col.vo),
        flow: cell(col.flow) || undefined,
      });
    }
  }
  return seqs.filter((s) => s.shots.length > 0);
}
