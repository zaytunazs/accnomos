import type { Page, Route } from "@playwright/test";
import { createBooksFolder, expect, signIn, test } from "./fixtures";

/**
 * Notes, to-dos and the calendar from the assistant (app/assistant_tasks.py), and verbal approval of its cards
 * (lib/voiceApproval.ts): a clear yes sends the same signed approval as the button, marked as spoken; no leaves the
 * card; a card that moves money always needs the tap.
 */

async function openAssistant(page: Page) {
  await page.getByRole("button", { name: "Talk to Accnomos" }).click();
  return page.getByRole("dialog", { name: "Talk to Accnomos" });
}

test("a typed note and a calendar event are saved through their cards; the Notes page lists and deletes", async ({ page }) => {
  await signIn(page);
  await createBooksFolder(page);
  await page.goto("/");
  const drawer = await openAssistant(page);

  await drawer.getByLabel("Your question").fill("take a note: ring the scaffolder about Friday");
  await drawer.getByRole("button", { name: "Send" }).click();
  const note = drawer.getByRole("article", { name: "Proposed: Note" });
  await expect(note).toContainText("Ring the scaffolder about Friday");
  await note.getByRole("button", { name: "Approve" }).click();
  await expect(note.getByRole("status")).toContainText("Saved");

  await drawer.getByLabel("Your question").fill("add a meeting with Hartwell tomorrow at 10");
  await drawer.getByRole("button", { name: "Send" }).click();
  const event = drawer.getByRole("article", { name: "Proposed: Add to calendar" });
  await expect(event).toContainText("Meeting with Hartwell");
  await expect(event).toContainText("10:00–11:00");
  await event.getByRole("button", { name: "Approve" }).click();
  await expect(event.getByRole("status")).toContainText("to your calendar");

  await drawer.getByLabel("Your question").fill("what's on my calendar tomorrow?");
  await drawer.getByRole("button", { name: "Send" }).click();
  await expect(drawer.getByRole("article").last()).toContainText("Meeting with Hartwell");

  await page.keyboard.press("Escape");
  await page.goto("/notes");
  const list = page.getByRole("list", { name: "Your notes" });
  await expect(list).toContainText("Ring the scaffolder about Friday");
  await list.getByRole("button", { name: /^Delete note:/ }).click();
  await list.getByRole("group", { name: "Confirm delete" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("No notes yet.")).toBeVisible();
});

/** A microphone that speaks for 0.8 s on every turn, and a speech engine that records what it was asked to say. */
async function fakeVoice(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __spoken: string[] };
    w.__spoken = [];
    navigator.mediaDevices.getUserMedia = async () => {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.9, ctx.currentTime);
      gain.gain.setValueAtTime(0, ctx.currentTime + 0.8);
      osc.connect(gain);
      const dest = ctx.createMediaStreamDestination();
      gain.connect(dest);
      osc.start();
      return dest.stream;
    };
    const synth = {
      speak(u: SpeechSynthesisUtterance) {
        w.__spoken.push(u.text);
        setTimeout(() => u.onend?.(new Event("end") as SpeechSynthesisEvent), 30);
      },
      cancel() {},
      getVoices: () => [],
    };
    Object.defineProperty(window, "speechSynthesis", { value: synth, configurable: true });
  });
}

const spoken = (page: Page) => page.evaluate(() => (window as unknown as { __spoken: string[] }).__spoken.join(" | "));

/** Speech-to-text is off in test mode: the voice route asks the real /books/ask with `question` (so the card is signed). */
async function hearQuestion(page: Page, question: string) {
  await page.route("**/books/ask/voice**", async (route: Route) => {
    const req = route.request();
    const res = await route.fetch({
      url: req.url().replace("/books/ask/voice", "/books/ask"),
      method: "POST",
      headers: { ...req.headers(), "content-type": "application/json" },
      postData: JSON.stringify({ question }),
    });
    const answer = await res.json();
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...answer, transcript: question, transcribed_by: null }) });
  });
}

function hearReplies(page: Page, replies: string[]) {
  let i = 0;
  return page.route("**/books/ask/transcribe", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ transcript: replies[Math.min(i++, replies.length - 1)], transcribed_by: null }) }),
  );
}

function approvals(page: Page): Record<string, unknown>[] {
  const seen: Record<string, unknown>[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/actions/approve") && r.method() === "POST") seen.push(r.postDataJSON() as Record<string, unknown>);
  });
  return seen;
}

test("hands-free: the card is read back and a spoken yes approves it, marked as spoken", async ({ page }) => {
  await fakeVoice(page);
  await signIn(page);
  await createBooksFolder(page);
  await hearQuestion(page, "take a note: order more screws");
  await hearReplies(page, ["Yes please", "stop"]);
  const sent = approvals(page);

  await page.goto("/");
  const drawer = await openAssistant(page);
  await drawer.getByRole("button", { name: "Hands-free" }).click();
  const card = drawer.getByRole("article", { name: "Proposed: Note" });
  await expect(card).toContainText("Order more screws", { timeout: 15_000 });
  await expect.poll(() => spoken(page), { timeout: 15_000 }).toContain("Shall I go ahead? Say yes or no.");
  await expect(card.getByRole("status")).toContainText("Saved", { timeout: 15_000 });
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({ via: "voice", heard: "Yes please" });
  await drawer.getByRole("button", { name: "Stop hands-free" }).click();
});

test("push-to-talk: no, or two unclear replies, leave the card on screen and approve nothing", async ({ page }) => {
  await fakeVoice(page);
  await signIn(page);
  await createBooksFolder(page);
  await hearQuestion(page, "add a meeting with Hartwell tomorrow at 10");
  await hearReplies(page, ["hmm", "what was that", "no"]);
  const sent = approvals(page);

  await page.goto("/");
  const drawer = await openAssistant(page);
  await drawer.getByRole("button", { name: "Ask by voice" }).click();
  const card = drawer.getByRole("article", { name: "Proposed: Add to calendar" });
  await expect(card).toContainText("Meeting with Hartwell", { timeout: 15_000 });
  await expect.poll(() => spoken(page), { timeout: 20_000 }).toContain("Nothing has changed");
  expect(await spoken(page)).toContain("10 am to 11 am"); // times read as words
  expect(await spoken(page)).toContain("Sorry, I didn't catch that.");
  expect(sent).toHaveLength(0);
  await expect(card.getByRole("button", { name: "Approve" })).toBeEnabled();
});

test("a card that moves money says it needs a tap and never takes a spoken yes", async ({ page }) => {
  await fakeVoice(page);
  await signIn(page);
  await createBooksFolder(page);
  const now = new Date();
  const later = new Date(now.getTime() + 15 * 60_000);
  await page.route("**/books/ask/voice**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        transcript: "chase Sterling for INV-0007",
        transcribed_by: null,
        answer_md: "Send a payment reminder for INV-0007.",
        confidence: "high",
        fallback_reason: null,
        key_numbers: [],
        citations: [],
        suggested_actions: [],
        model: "code",
        period: null,
        proposed_action: {
          id: "0".repeat(32),
          kind: "chase_invoice",
          summary_md: "Email a payment reminder for **INV-0007** (£480.00) to Sterling & Co.",
          preview: { invoice: "INV-0007", customer: "Sterling & Co.", total_pence: 48000, due_date: "2026-10-01", days_overdue: 26, to: "accounts@sterling.example", subject: "INV-0007", body: "Hello" },
          confirm_text: "Send this reminder",
          created_at: now.toISOString(),
          expires_at: later.toISOString(),
          tap_only: true,
          signature: "x",
        },
      }),
    }),
  );
  await hearReplies(page, ["yes"]);
  const sent = approvals(page);

  await page.goto("/");
  const drawer = await openAssistant(page);
  await drawer.getByRole("button", { name: "Hands-free" }).click();
  const card = drawer.getByRole("article", { name: "Proposed: Payment reminder" });
  await expect(card).toContainText("needs a tap on Approve", { timeout: 15_000 });
  await expect.poll(() => spoken(page), { timeout: 15_000 }).toContain("needs you to tap Approve");
  expect(await spoken(page)).toContain("four hundred and eighty pounds");
  await expect(drawer.getByText("Hands-free paused: the card is on screen to tap.")).toBeVisible();
  expect(sent).toHaveLength(0);
});
