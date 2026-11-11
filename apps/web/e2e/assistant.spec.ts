import { createBooksFolder, expect, signIn, test } from "./fixtures";

/** "Talk to Accnomos": the floating button, a typed question, and one hands-free turn with a faked microphone. */

test("the assistant opens from any page, answers a typed question, and closes with Esc", async ({ page, runtime }) => {
  await signIn(page);
  await createBooksFolder(page);
  await runtime.postGold();

  await page.goto("/bank");
  const open = page.getByRole("button", { name: "Talk to Accnomos" });
  await expect(open).toBeVisible();
  await open.click();

  const drawer = page.getByRole("dialog", { name: "Talk to Accnomos" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByLabel("Your question")).toBeFocused();
  await expect(drawer.getByRole("button", { name: "Who owes me the most?" })).toBeVisible(); // business starters

  await drawer.getByLabel("Your question").fill("How much VAT do I owe and why?");
  await drawer.getByRole("button", { name: "Send" }).click();
  await expect(drawer.getByRole("article")).toContainText("Numbers by code · explanation by accnomos-test-stub");

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(open).toBeFocused();

  // The conversation is kept for the tab: reopening shows it.
  await open.click();
  await expect(page.getByRole("dialog", { name: "Talk to Accnomos" })).toContainText("How much VAT do I owe and why?");
});

test("hands-free: listens, sends what it heard, reads the answer aloud, stops on two quiet turns", async ({ page }) => {
  // A microphone that "speaks" for 0.8 s then goes quiet, and a speech engine that records what it was asked to say.
  await page.addInitScript(() => {
    const w = window as unknown as { __spoken: string[]; __mics: number };
    w.__spoken = [];
    w.__mics = 0;
    navigator.mediaDevices.getUserMedia = async () => {
      w.__mics += 1;
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      // only the first turn has speech: later turns are silent, so hands-free ends after two empty turns
      gain.gain.setValueAtTime(w.__mics === 1 ? 0.9 : 0, ctx.currentTime);
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
        setTimeout(() => u.onend?.(new Event("end") as SpeechSynthesisEvent), 50);
      },
      cancel() {},
      getVoices: () => [],
    };
    Object.defineProperty(window, "speechSynthesis", { value: synth, configurable: true });
  });
  await signIn(page);
  await createBooksFolder(page);

  // Speech-to-text is off in test mode: answer the voice route as the live runtime would.
  await page.route("**/books/ask/voice**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        transcript: "Who owes me the most?",
        transcribed_by: { name: "muse", label: "the speech-to-text model", model: "muse-voice-transcribe-1.0" },
        answer_md: "**Sterling & Co.** owes you the most: £7,479.60.",
        confidence: "high",
        fallback_reason: null,
        key_numbers: [],
        citations: [],
        suggested_actions: [],
        model: "code",
        period: null,
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Talk to Accnomos" }).click();
  const drawer = page.getByRole("dialog", { name: "Talk to Accnomos" });
  await drawer.getByRole("button", { name: "Hands-free" }).click();
  await expect(drawer.getByRole("button", { name: "Stop hands-free" })).toBeVisible();

  await expect(drawer).toContainText("Who owes me the most?", { timeout: 15_000 });
  await expect(drawer).toContainText("Transcribed by the speech-to-text model");
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __spoken: string[] }).__spoken.join(" | ")))
    .toContain("Sterling & Co. owes you the most: £7,479.60."); // markdown stripped before speaking

  // Two quiet turns (8 s each) end hands-free.
  await expect(drawer.getByText("Hands-free stopped: I didn't hear anything.")).toBeVisible({ timeout: 30_000 });
  await expect(drawer.getByRole("button", { name: "Hands-free" })).toBeVisible();
});
