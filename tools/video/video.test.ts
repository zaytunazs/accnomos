/**
 * Unit tests for the parts of tools/video that decide what gets recorded: `node --test tools/video/video.test.ts`.
 * (The capture itself is checked by eye on the contact sheets; it needs a browser and the test-mode runtime.)
 */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { chooseFlow, FLOWS, SHOT_PLAN } from "./flows.ts";
import { candidates, findPlaceholders } from "./howto.ts";
import { parseDuration, parseScript } from "./lib/script.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const tmp = mkdtempSync(path.join(tmpdir(), "video-test-"));

function file(name: string, text: string): string {
  const p = path.join(tmp, name);
  writeFileSync(p, text);
  return p;
}

test("durations: ranges, lengths and stage directions", () => {
  assert.equal(parseDuration("0:07–0:17", true), 10);
  assert.equal(parseDuration("0:14–0:25 (11 s, ≤ 27)", true), 11);
  assert.equal(parseDuration("7 s", false), 7);
  assert.equal(parseDuration("0:12", false), 12);
  assert.ok(Number.isNaN(parseDuration("7 s", true)));
});

test("table layout: one sequence per clip heading, voice-over without its word count", () => {
  const p = file(
    "CLIPS.md",
    [
      "# Clips",
      "## Clip 3 — VAT return and MTD (0:00–0:35)",
      "| Time | Screen | On-screen action | Caption | Voice-over |",
      "|---|---|---|---|---|",
      '| 0:00–0:15 (15 s, ≤ 37) | VAT return (`/vat`) | Open the picker | `Nine boxes by code` | "The nine boxes." (3 words) |',
      "| 0:15–0:35 (20 s) | VAT return | Submit | `Sandbox only (if it fails: stop)` | Plain words |",
    ].join("\n"),
  );
  const [seq, ...rest] = parseScript(p, "clip");
  assert.equal(rest.length, 0);
  assert.equal(seq!.id, "clip-03");
  assert.equal(seq!.title, "VAT return and MTD");
  assert.deepEqual(
    seq!.shots.map((s) => [s.id, s.duration, s.caption, s.vo]),
    [
      ["clip-03-01", 15, "Nine boxes by code", "The nine boxes."],
      ["clip-03-02", 20, "Sandbox only", "Plain words"],
    ],
  );
  assert.match(seq!.shots[0]!.what, /^VAT return \(\/vat\): Open the picker$/);
});

test("section layout: shot headings, card text from a quote, end card from the action", () => {
  const p = file(
    "JUDGES.md",
    [
      "# Judges' video",
      "## Shot 1 — before the event (0:00–0:08, 8 s)",
      "Screen: black card.",
      "",
      "> Line one.",
      "> Line two.",
      "",
      "Caption: `Only Spark hardware predates the event` (6 words).",
      "",
      'Voice-over (3 words): "Before the hackathon."',
      "### Shot 2 — end (0:08–0:20, 12 s)",
      "Screen: Ask (`/ask`).",
      "",
      "On-screen action: type; cut to the end card: `github.com/x · Sample data`.",
    ].join("\n"),
  );
  const [seq] = parseScript(p, "judges");
  assert.equal(seq!.shots.length, 2);
  assert.deepEqual([seq!.shots[0]!.duration, seq!.shots[1]!.duration], [8, 12]);
  assert.equal(seq!.shots[0]!.card, "Line one.\nLine two.");
  assert.equal(seq!.shots[0]!.caption, "Only Spark hardware predates the event");
  assert.equal(seq!.shots[0]!.vo, "Before the hackathon.");
  assert.equal(seq!.shots[1]!.endCard, "github.com/x · Sample data");
});

test("Muse's scripts: 180 s judges' video, every shot planned with a known flow", () => {
  const judges = parseScript(path.join(ROOT, "docs/video/JUDGES_VIDEO.md"), "judges")[0]!;
  assert.equal(judges.shots.reduce((t, s) => t + s.duration, 0), 180);
  assert.match(judges.shots[0]!.card ?? "", /Before the hackathon I had only my DGX Spark with Ollama/);
  const clips = parseScript(path.join(ROOT, "docs/video/CLIPS.md"), "clip");
  assert.equal(clips.length, 8);
  for (const s of [...judges.shots, ...clips.flatMap((c) => c.shots)]) {
    assert.ok(SHOT_PLAN[s.id], `${s.id} has no line in SHOT_PLAN`);
    assert.ok(FLOWS[chooseFlow(s)], `${s.id}: unknown flow`);
  }
});

test("keyword rules pick a flow when a shot is not in the plan", () => {
  assert.equal(chooseFlow({ what: "VAT return → Connect to HMRC (sandbox)", caption: "" }), "hmrc-sim");
  assert.equal(chooseFlow({ what: "Black card, white text", caption: "" }), "card");
  assert.equal(chooseFlow({ what: "Something new", caption: "", flow: "bank" }), "bank");
});

test("how-to placeholders: numbered from the file name, brief from 'Must be visible', controls from the step", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "howto-"));
  const p = path.join(dir, "vat-return.md");
  writeFileSync(
    p,
    [
      "# Do a VAT return",
      "3. Press *Connect to HMRC (sandbox)* and sign in.",
      "   ![step 3](../howto/img/vat-return-3.png)",
      "   Must be visible: the sandbox connect button and the",
      "   HMRC sign-in.",
      "   If this goes wrong: retry.",
    ].join("\n"),
  );
  const [ph] = findPlaceholders(p);
  assert.equal(ph!.n, 3);
  assert.equal(ph!.alt, "the sandbox connect button and the HMRC sign-in.");
  assert.equal(ph!.visibleEnd, 5); // the two "Must be visible" lines are replaced with the image
  assert.deepEqual(candidates({ ...ph!, target: undefined }), ["Connect to HMRC (sandbox)"]);
});
