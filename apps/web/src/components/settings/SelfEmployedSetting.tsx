"use client";

import Link from "next/link";
import { setSelfEmployed, useSelfEmployed } from "@/lib/itsa";

/** Settings › Business › "I am self-employed": shows Self-employment (MTD Income Tax) in the menu. Off by default. */
export default function SelfEmployedSetting({ card, heading }: { card: string; heading: string }) {
  const on = useSelfEmployed();
  return (
    <section aria-labelledby="settings-self-employed" className={card}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="settings-self-employed" className={heading}>I am self-employed</h3>
          <p className="mt-1 text-sm text-muted">
            Adds Self-employment to the menu: quarterly updates for Making Tax Digital for Income Tax, worked out from your
            approved entries and sent to HMRC&apos;s sandbox when you confirm.{" "}
            {on && <Link href="/self-employment" className="font-bold text-teal-dark">Open Self-employment</Link>}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="I am self-employed"
          onClick={() => setSelfEmployed(!on)}
          className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition-colors ${on ? "bg-teal" : "bg-border"}`}
        >
          <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
        </button>
      </div>
    </section>
  );
}
