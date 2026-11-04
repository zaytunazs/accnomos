"use client";

import { useEffect, useState } from "react";
import {
  AI_ROUTE_INTRO,
  AI_ROUTE_OPTIONS,
  DEFAULT_AI_ROUTE,
  LOCAL_ONLY_WARNINGS,
  LOCAL_ONLY_WARNING_TITLE,
  loadAiRoute,
  saveAiRoute,
  type AiRoute,
} from "@/lib/ai-route";

/**
 * "Which AI answers first": shown only where the AI is set up (the AI step of /connect and Settings › AI, both via
 * ChooseAi). A choice is saved on this device the moment it is picked and sent as `X-AI-Route` from then on.
 */
export default function AiRouteChoice() {
  const [route, setRoute] = useState<AiRoute>(DEFAULT_AI_ROUTE);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const r = loadAiRoute();
    if (!r) return;
    queueMicrotask(() => setRoute(r)); // defer: no synchronous setState in the effect body
  }, []);

  function choose(r: AiRoute) {
    setRoute(r);
    saveAiRoute(r);
    setSaved(true);
  }

  return (
    <section aria-labelledby="ai-route-heading" className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
      <h3 id="ai-route-heading" className="text-[17px] font-extrabold text-[#1B1F24]">
        Which AI answers first
      </h3>
      <p id="ai-route-intro" className="mt-1 text-sm text-[#4B5159]">
        {AI_ROUTE_INTRO}
      </p>
      <div role="radiogroup" aria-labelledby="ai-route-heading" aria-describedby="ai-route-intro" className="mt-3 space-y-2">
        {AI_ROUTE_OPTIONS.map((opt) => {
          const id = `ai-route-${opt.value}`;
          const active = route === opt.value;
          const localOnly = opt.value === "local_only";
          return (
            <div
              key={opt.value}
              className={`rounded-xl border p-3 ${active ? "border-2 border-[#5A2D00] bg-[#F4EDE5]/40" : "border-[#E3E1D8]"}`}
            >
              <label htmlFor={id} className="flex cursor-pointer items-start gap-3">
                <input
                  id={id}
                  type="radio"
                  name="ai-route"
                  value={opt.value}
                  checked={active}
                  onChange={() => choose(opt.value)}
                  aria-describedby={localOnly ? `${id}-desc ai-route-local-warning` : `${id}-desc`}
                  className="mt-1 h-5 w-5 shrink-0 accent-[#5A2D00]"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-[15px] font-extrabold text-[#1B1F24]">{opt.label}</span>
                    {opt.badge && (
                      <span className="rounded-full bg-[#F4EDE5] px-2 py-0.5 text-[11px] font-extrabold text-[#3F2000]">
                        {opt.badge}
                      </span>
                    )}
                  </span>
                  <span id={`${id}-desc`} className="mt-0.5 block text-sm text-[#4B5159]">
                    {opt.description}
                  </span>
                </span>
              </label>
              {localOnly && (
                <div
                  id="ai-route-local-warning"
                  data-testid="ai-route-local-warning"
                  data-selected={active ? "true" : "false"}
                  className={`mt-3 rounded-xl border p-3 text-sm ${
                    active ? "border-[#F3C892] bg-[#FFF7ED] text-[#8A3F06]" : "border-[#E3E1D8] bg-[#F9F8F4] text-[#4B5159]"
                  }`}
                >
                  <p className="font-extrabold">{LOCAL_ONLY_WARNING_TITLE}</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {LOCAL_ONLY_WARNINGS.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {saved && (
        <p role="status" className="mt-2 text-sm font-bold text-[#3F2000]">
          Saved on this device.
        </p>
      )}
    </section>
  );
}
