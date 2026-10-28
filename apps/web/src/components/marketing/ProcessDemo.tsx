"use client";

import { useEffect, useRef, useState } from "react";
import { BrowserFrame } from "./Marks";

type Box = { left: number; top: number; width: number; height: number }; // percent of the screenshot

type Step = {
  title: string;
  body: string;
  src: string;
  width: number;
  height: number;
  alt: string;
  mark: Box;
};

/**
 * One receipt from photo to VAT box, on real screens (scripts/marketing-images.py crops them from
 * docs/submission/shots). The highlight boxes are percentages of those crops; nothing on the screens is drawn.
 */
const STEPS: Step[] = [
  {
    title: "Snap it on your phone",
    body: "Take a photo in the Android app. It lands in 00 Inbox in your OneDrive; email intake, web upload and dropping the file in work too.",
    src: "/shots/step-1-receipt.webp",
    width: 750,
    height: 640,
    alt: "A photographed till receipt from Novex Office Supplies Ltd: two items, net £43.25, VAT £8.65, total £51.90, paid by card. Stamped sample, fictional company.",
    mark: { left: 17, top: 52, width: 54, height: 22 },
  },
  {
    title: "A Meta model reads it",
    body: "Muse Glimmer 30B reads the supplier, date, VAT number, lines and totals into strict fields, and says how sure it is.",
    src: "/shots/step-2-read.webp",
    width: 816,
    height: 510,
    alt: "The Review card for Novex Office Supplies Ltd, £51.90: confidence 97 %, read by Glimmer 30B, date 2 Nov 2026, VAT number GB 882431902, net £43.25, VAT £8.65, paid by card ending 4821, and the proposed entry.",
    mark: { left: 29, top: 15, width: 53, height: 9 },
  },
  {
    title: "Code checks it",
    body: "The lines and totals must add up, and a second reading checks the first. The card says why in plain words.",
    src: "/shots/step-3-check.webp",
    width: 816,
    height: 510,
    alt: "The proposed entry (office supplies £43.25, VAT to reclaim £8.65, paid from business card £51.90), the line “Why: 2 lines, totals add up (43.25 + 8.65 = 51.90) — Checker, code”, and the verifier agreeing on all six fields.",
    mark: { left: 4, top: 53, width: 92, height: 32 },
  },
  {
    title: "You approve, on phone or web",
    body: "The same card waits on the phone and on the web. Nothing is posted until you tap Approve; then one balanced entry is written, and Undo is one tap away.",
    src: "/shots/step-4-approved.webp",
    width: 816,
    height: 510,
    alt: "The Review page after approving: “Approved · Autopilot will do this for Novex Office Supplies Ltd next time · U to undo”, and nothing left waiting.",
    mark: { left: 2, top: 8.5, width: 95, height: 9 },
  },
  {
    title: "The VAT box fills",
    body: "Code adds the £8.65 to Box 4 of that period's return, and Box 5 follows. Sending it to HMRC is sandbox only for now.",
    src: "/shots/step-5-vat.webp",
    width: 816,
    height: 510,
    alt: "The nine-box VAT return: Box 4, VAT reclaimed on purchases, £8.65 from 1 entry; Box 5, net VAT, £8.65; Box 7, purchases excluding VAT, £43.",
    mark: { left: 3, top: 32.5, width: 93, height: 19 },
  },
];

const STEP_MS = 4800;

/**
 * The process animation: five step buttons and one stage. It plays while on screen (unless the visitor asked for
 * reduced motion, or pressed Pause), moving a highlight over the part of each real screen that matters.
 */
export default function ProcessDemo() {
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false); // starts once visible, and only without prefers-reduced-motion
  const [paused, setPaused] = useState(false); // the visitor's choice wins over everything else
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches || !root.current || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setPlaying(entry.isIntersecting), { threshold: 0.35 });
    io.observe(root.current);
    return () => io.disconnect();
  }, []);

  const running = playing && !paused;
  useEffect(() => {
    if (!running) return;
    const t = window.setTimeout(() => setActive((a) => (a + 1) % STEPS.length), STEP_MS);
    return () => window.clearTimeout(t);
  }, [running, active]);

  const pick = (i: number) => {
    setActive(i);
    setPaused(true); // someone chose a step: stay on it
  };

  return (
    <div ref={root} className="grid items-start gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12">
      <div>
        <ol className="flex flex-col gap-1" aria-label="Steps">
          {STEPS.map((s, i) => {
            const on = i === active;
            return (
              <li key={s.title}>
                <button
                  type="button"
                  onClick={() => pick(i)}
                  aria-current={on ? "step" : undefined}
                  aria-controls="process-stage"
                  className={`group relative w-full overflow-hidden rounded-xl px-4 py-3 text-left transition-colors ${
                    on ? "bg-white shadow-sm" : "hover:bg-white/60"
                  }`}
                >
                  <span className="flex items-baseline gap-3">
                    <span
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-extrabold tabular-nums ${
                        on ? "bg-teal text-white" : "bg-border text-muted"
                      }`}
                    >
                      {i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className={`block text-base font-extrabold ${on ? "text-ink" : "text-muted"}`}>
                        {s.title}
                      </span>
                      <span className={`mt-1 block text-sm leading-relaxed text-muted ${on ? "" : "max-lg:hidden"}`}>
                        {s.body}
                      </span>
                    </span>
                  </span>
                  {on && (
                    <span
                      aria-hidden="true"
                      key={`${active}-${running}`}
                      className={`demo-progress absolute inset-x-0 bottom-0 h-[3px] origin-left bg-teal ${running ? "" : "demo-progress-still"}`}
                      style={{ animationDuration: `${STEP_MS}ms` }}
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ol>
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          className="mt-3 rounded-lg px-4 py-2 text-sm font-bold text-teal-dark underline underline-offset-2 hover:text-teal"
        >
          {paused ? "Play the steps" : "Pause the steps"}
        </button>
      </div>

      <figure>
        <BrowserFrame>
          <div id="process-stage" className="relative aspect-[8/5] overflow-hidden bg-[#57493d]">
            {STEPS.map((s, i) => (
              <div
                key={s.src}
                aria-hidden={i !== active}
                className={`absolute inset-0 flex items-center justify-center transition-opacity duration-500 ${
                  i === active ? "opacity-100" : "opacity-0"
                } ${i === 0 ? "" : "bg-ground"}`}
              >
                <div className="relative h-full max-w-full" style={{ aspectRatio: `${s.width} / ${s.height}` }}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- static export, unoptimised images */}
                  <img
                    src={s.src}
                    alt={i === active ? s.alt : ""}
                    width={s.width}
                    height={s.height}
                    loading="lazy"
                    decoding="async"
                    className="block h-full w-full"
                  />
                  <span
                    aria-hidden="true"
                    className={`demo-mark ${i === active ? "demo-mark-on" : ""}`}
                    style={{
                      left: `${s.mark.left}%`,
                      top: `${s.mark.top}%`,
                      width: `${s.mark.width}%`,
                      height: `${s.mark.height}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </BrowserFrame>
        <figcaption className="mt-3 text-[13px] leading-relaxed text-muted">
          <span className="font-bold text-ink">
            Step {active + 1} of {STEPS.length}: {STEPS[active].title}.
          </span>{" "}
          Real screens from the app in test mode with the fictional sample books; in test mode a stub stands in for
          the model.
        </figcaption>
      </figure>
    </div>
  );
}
