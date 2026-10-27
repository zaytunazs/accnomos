"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import OutlookIntake from "@/components/settings/OutlookIntake";
import AutopilotRules from "@/components/settings/AutopilotRules";
import VatPeriodSettings from "@/components/settings/VatPeriodSettings";
import { RUNTIME_URL } from "@/lib/ai-config";

type AutopilotLevel = "L0" | "L1" | "L2";

const AUTOPILOT_KEY = "accnomos.autopilot";
const AI_KEY = "accnomos.ai";

const AUTOPILOT_OPTIONS: { value: AutopilotLevel; label: string; description: string }[] = [
  { value: "L0", label: "L0 Suggest", description: "Nothing automatic; everything is a proposal" },
  { value: "L1", label: "L1 Assist", description: "Imports, extracts, files and proposes; never posts or sends (default)" },
  { value: "L2", label: "L2 Autopilot", description: "Also posts receipts that match a rule you saved (same supplier, VAT and treatment, ≤ 2× the usual) — each one listed with Undo" },
];

function readLocalStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

const card = "rounded-2xl border border-border bg-white p-4";
const heading = "text-[17px] font-extrabold text-ink";
const groupHeading = "text-lg font-extrabold tracking-tight text-ink";
const groupIntro = "mt-1 text-sm leading-6 text-muted";

function Group({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div>
        <h2 id={id} className={groupHeading}>
          {title}
        </h2>
        <p className={groupIntro}>{intro}</p>
      </div>
      {children}
    </section>
  );
}

export default function SettingsPanels() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [aiSummary, setAiSummary] = useState("Not set up");
  const [autopilot, setAutopilot] = useState<AutopilotLevel>("L1");
  const [disconnected, setDisconnected] = useState(false);

  useEffect(() => {
    // Defer to avoid synchronous setState in the effect body.
    queueMicrotask(() => {
      try {
        const keys: string[] = [];
        for (let i = 0; i < window.localStorage.length; i++) {
          const k = window.localStorage.key(i);
          if (k) keys.push(k);
        }
        setSignedIn(keys.some((k) => k.startsWith("msal.")));
      } catch {
        setSignedIn(false);
      }

      const rawAi = readLocalStorage(AI_KEY);
      if (rawAi) {
        try {
          const parsed = JSON.parse(rawAi) as { mode?: string; model?: string };
          setAiSummary(
            parsed.mode && parsed.model ? `${parsed.mode} · ${parsed.model}` : "Set up",
          );
        } catch {
          setAiSummary("Set up");
        }
      }

      const rawAuto = readLocalStorage(AUTOPILOT_KEY);
      if (rawAuto === "L0" || rawAuto === "L1" || rawAuto === "L2") setAutopilot(rawAuto);
    });
  }, []);

  function chooseAutopilot(level: AutopilotLevel) {
    setAutopilot(level);
    try {
      window.localStorage.setItem(AUTOPILOT_KEY, level);
    } catch {
      /* storage unavailable — level lives for this page only */
    }
  }

  function disconnect() {
    try {
      const doomed: string[] = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const k = window.localStorage.key(i);
        if (k && (k.startsWith("accnomos.") || k.startsWith("msal."))) doomed.push(k);
      }
      for (const k of doomed) window.localStorage.removeItem(k);
    } catch {
      /* ignore */
    }
    setSignedIn(false);
    setAiSummary("Not set up");
    setDisconnected(true);
  }

  return (
    <div className="mt-6 flex flex-col gap-8">
      <Group
        id="settings-group-connection"
        title="Connection"
        intro="Where your books live and how this device reaches them."
      >
        <section aria-labelledby="settings-connections" className={card}>
          <h3 id="settings-connections" className={heading}>
            Connections
          </h3>
          <dl className="mt-3 divide-y divide-border">
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">Microsoft</dt>
              <dd className="text-sm text-muted">
                {signedIn === null ? "Checking…" : signedIn ? "Signed in" : "Not signed in"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">HMRC</dt>
              <dd className="flex items-center gap-3">
                <span className="text-sm text-muted">Sandbox · not connected</span>
                <button
                  type="button"
                  disabled
                  className="h-10 whitespace-nowrap rounded-xl border border-border bg-ground px-4 text-sm font-bold text-muted disabled:opacity-60"
                >
                  Connect HMRC (sandbox)
                </button>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">Google Drive</dt>
              <dd>
                <span className="rounded-full bg-ground px-2 py-0.5 text-[11px] font-extrabold text-muted">
                  Coming next
                </span>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">Reader address</dt>
              <dd className="min-w-0 break-all text-right font-mono text-[13px] text-muted">
                {RUNTIME_URL}
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="settings-disconnect" className={card}>
          <h3 id="settings-disconnect" className={heading}>
            Disconnect
          </h3>
          <p className="mt-1 text-sm text-muted">
            Your files stay in your OneDrive. We remove this device&apos;s sign-in and settings.
          </p>
          <button
            type="button"
            onClick={disconnect}
            className="mt-3 h-12 whitespace-nowrap rounded-xl border-2 border-teal bg-white px-5 text-[15px] font-extrabold text-teal-dark"
          >
            Disconnect Accnomos
          </button>
          {disconnected && (
            <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
              Disconnected.
            </p>
          )}
        </section>
      </Group>

      <Group
        id="settings-group-ai"
        title="AI"
        intro="Which AI reads your receipts and answers your questions. Keys and addresses never leave this device."
      >
        <section aria-labelledby="settings-ai" className={card}>
          <h3 id="settings-ai" className={heading}>
            AI setup
          </h3>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 py-1">
            <p className="min-w-0 text-[15px] font-bold break-words text-ink">
              Current: <span className="font-medium text-muted">{aiSummary}</span>
            </p>
            <Link
              href="/connect/ai"
              className="shrink-0 whitespace-nowrap rounded-xl border-2 border-teal bg-white px-4 py-2 text-sm font-bold text-teal-dark"
            >
              Choose AI
            </Link>
          </div>
        </section>
      </Group>

      <Group
        id="settings-group-automation"
        title="Automation"
        intro="What Accnomos may do on its own. At L0 and L1 nothing is posted or sent without you."
      >
        <OutlookIntake card={card} heading={heading} />

        <section aria-labelledby="settings-autopilot" className={card}>
          <h3 id="settings-autopilot" className={heading}>
            Autopilot level
          </h3>
          <div className="mt-3 space-y-2" role="radiogroup" aria-label="Autopilot level">
            {AUTOPILOT_OPTIONS.map((opt) => {
              const active = autopilot === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => chooseAutopilot(opt.value)}
                  className={`block w-full rounded-2xl border p-4 text-left ${
                    active ? "border-2 border-teal bg-teal-tint" : "border-border"
                  }`}
                >
                  <span className="text-[15px] font-extrabold text-ink">{opt.label}</span>
                  <span className="mt-1 block text-sm text-muted">{opt.description}</span>
                </button>
              );
            })}
          </div>
        </section>

        <AutopilotRules card={card} heading={heading} />
      </Group>

      <Group
        id="settings-group-business"
        title="Business"
        intro="Your details for VAT periods and deadlines. Saved on this device."
      >
        <VatPeriodSettings card={card} heading={heading} />

        <section aria-labelledby="settings-audit" className={card}>
          <h3 id="settings-audit" className={heading}>
            Audit log
          </h3>
          <Link href="#" className="mt-2 inline-block text-sm font-bold text-teal-dark">
            Open _System/audit in OneDrive
          </Link>
        </section>
      </Group>
    </div>
  );
}
