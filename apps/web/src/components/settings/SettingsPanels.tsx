"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ChooseAi from "@/components/ChooseAi";
import InboxTriageSetting from "@/components/settings/InboxTriageSetting";
import YourData from "@/components/settings/YourData";
import OutlookIntake from "@/components/settings/OutlookIntake";
import EmailIntake from "@/components/settings/EmailIntake";
import AutopilotRules from "@/components/settings/AutopilotRules";
import BusinessDetails from "@/components/settings/BusinessDetails";
import ProfileDetails from "@/components/settings/ProfileDetails";
import StaffEditor from "@/components/settings/StaffEditor";
import VatPeriodSettings from "@/components/settings/VatPeriodSettings";
import SelfEmployedSetting from "@/components/settings/SelfEmployedSetting";
import VatSchemeSettings from "@/components/settings/VatSchemeSettings";
import InvoiceProfileForm from "@/components/invoices/InvoiceProfileForm";
import PersonalFinanceSetting from "@/components/settings/PersonalFinanceSetting";
import LandlordSetting from "@/components/settings/LandlordSetting";
import WorkingHours from "@/components/settings/WorkingHours";
import YourAccountant from "@/components/settings/YourAccountant";
import FilesBackups from "@/components/settings/FilesBackups";
import OnlinePayments from "@/components/settings/OnlinePayments";
import { hasMsalSignIn } from "@/lib/signed-in";

type AutopilotLevel = "L0" | "L1" | "L2";
type GroupId = "connection" | "ai" | "automation" | "business" | "accountant" | "files" | "data";

const AUTOPILOT_KEY = "accnomos.autopilot";
const AI_KEY = "accnomos.ai";
const GROUP_KEY = "accnomos.settings.group";

const GROUPS: { id: GroupId; label: string }[] = [
  { id: "connection", label: "Connection" },
  { id: "ai", label: "AI" },
  { id: "automation", label: "Automation" },
  { id: "business", label: "Business" },
  { id: "accountant", label: "Your accountant" },
  { id: "files", label: "Files & backups" },
  { id: "data", label: "Your data" },
];

/** Every deep link target stays working: the hash decides which tab opens. Back from Stripe or PayPal the hash is
 *  `pay=stripe&code=…` (OnlinePayments reads it), which opens Business. */
function groupOf(raw: string): GroupId | null {
  if (raw.startsWith("pay=")) return "business";
  return (raw && HASH_GROUP[raw]) || null;
}

const HASH_GROUP: Record<string, GroupId> = {
  "settings-connections": "connection",
  "settings-audit": "connection",
  "settings-disconnect": "connection",
  "settings-ai": "ai",
  "settings-verifier": "ai",
  agent: "ai",
  lmodel: "ai",
  apikey: "ai",
  "settings-autopilot": "automation",
  "settings-rules": "automation",
  "settings-intake": "automation",
  "settings-email-intake": "automation",
  "email-intake": "automation",
  automation: "automation", // Home's "Turn on Inbox triage in Settings"
  "settings-automation": "automation",
  "settings-business-hours": "automation",
  "settings-business": "business",
  profile: "business", // the profile menu's "Profile details"
  "settings-vat-periods": "business",
  "settings-self-employed": "business",
  "settings-vat-scheme": "business",
  "settings-invoice-profile": "business",
  "invoice-profile": "business",
  "invoice-profile-title": "business",
  "settings-staff": "business",
  "settings-personal": "business",
  "settings-payments": "business",
  "settings-accountant": "accountant",
  accountant: "accountant",
  "settings-files": "files",
  "back-up-now": "files",
  "previous-files": "files",
  "settings-data": "data",
  "settings-data-import": "data",
  "settings-data-export": "data",
  "settings-leave": "data",
};

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

function writeLocalStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — the choice lives for this page only */
  }
}

export default function SettingsPanels() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [aiSummary, setAiSummary] = useState("Not set up");
  const [autopilot, setAutopilot] = useState<AutopilotLevel>("L1");
  const [disconnected, setDisconnected] = useState(false);
  const [group, setGroup] = useState<GroupId>("connection");
  const pendingHash = useRef<string | null>(null);

  function choose(g: GroupId) {
    setGroup(g);
    writeLocalStorage(GROUP_KEY, g);
  }

  function openHashTarget() {
    const raw = window.location.hash.replace(/^#/, "");
    const g = groupOf(raw);
    if (!g) return;
    pendingHash.current = raw.startsWith("pay=") ? "settings-payments" : raw;
    choose(g);
  }

  useEffect(() => {
    // Defer to avoid synchronous setState in the effect body.
    queueMicrotask(() => {
      try {
        const keys: string[] = [];
        for (let i = 0; i < window.localStorage.length; i++) {
          const k = window.localStorage.key(i);
          if (k) keys.push(k);
        }
        setSignedIn(hasMsalSignIn(keys, (k) => window.localStorage.getItem(k)));
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

      const rawHash = window.location.hash.replace(/^#/, "");
      const hashed = groupOf(rawHash);
      if (rawHash && hashed) pendingHash.current = rawHash.startsWith("pay=") ? "settings-payments" : rawHash;
      const stored = readLocalStorage(GROUP_KEY);
      const remembered =
        stored === "connection" || stored === "ai" || stored === "automation" || stored === "business" || stored === "data"
          ? stored
          : null;
      setGroup(hashed ?? remembered ?? "connection");
    });
    window.addEventListener("hashchange", openHashTarget);
    return () => window.removeEventListener("hashchange", openHashTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After the right tab is showing, bring the deep-linked section into view.
  useEffect(() => {
    if (!pendingHash.current) return;
    const el = document.getElementById(pendingHash.current);
    pendingHash.current = null;
    if (!el) return;
    el.scrollIntoView({ block: "start" });
    // Sections above it (invoice profile, staff) may still be loading and push it down: keep it in place while
    // the panel grows, for a few seconds or until the user scrolls or types.
    const panel = el.closest('[role="tabpanel"]');
    if (!panel || typeof ResizeObserver === "undefined") return;
    const keep = new ResizeObserver(() => el.scrollIntoView({ block: "start" }));
    keep.observe(panel);
    const stop = () => {
      keep.disconnect();
      for (const ev of ["wheel", "touchstart", "keydown"]) window.removeEventListener(ev, stop);
    };
    for (const ev of ["wheel", "touchstart", "keydown"]) window.addEventListener(ev, stop, { passive: true });
    window.setTimeout(stop, 3000);
  });

  function onTabKeys(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const order = GROUPS.map((g) => g.id);
    let i = order.indexOf(group);
    if (e.key === "ArrowRight") i = (i + 1) % order.length;
    else if (e.key === "ArrowLeft") i = (i - 1 + order.length) % order.length;
    else if (e.key === "Home") i = 0;
    else i = order.length - 1;
    choose(order[i]);
    document.getElementById(`tab-${order[i]}`)?.focus();
  }

  function chooseAutopilot(level: AutopilotLevel) {
    setAutopilot(level);
    writeLocalStorage(AUTOPILOT_KEY, level);
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

  const card = "rounded-2xl border border-border bg-white p-4";
  const heading = "text-[17px] font-extrabold text-ink";

  return (
    <div className="mt-6">
      <div
        role="tablist"
        aria-label="Settings groups"
        onKeyDown={onTabKeys}
        className="grid grid-cols-2 gap-2 min-[560px]:grid-cols-3"
      >
        {GROUPS.map((g) => {
          const active = group === g.id;
          return (
            <button
              key={g.id}
              type="button"
              role="tab"
              id={`tab-${g.id}`}
              aria-selected={active}
              aria-controls={`panel-${g.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => choose(g.id)}
              className={`h-11 whitespace-nowrap rounded-xl border px-3 text-[15px] font-bold ${
                active
                  ? "border-2 border-teal bg-teal-tint text-teal-dark"
                  : "border-border bg-white text-ink hover:bg-ground"
              }`}
            >
              {g.label}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id="panel-connection"
        aria-labelledby="tab-connection"
        hidden={group !== "connection"}
        className="mt-4 space-y-4"
      >
        <section aria-labelledby="settings-connections" className={card}>
          <h2 id="settings-connections" className={heading}>
            Connections
          </h2>
          <dl className="mt-3 divide-y divide-border">
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">Microsoft</dt>
              <dd className="text-sm text-muted">
                {signedIn === null ? "Checking…" : signedIn ? "Signed in" : "Not signed in"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">AI</dt>
              <dd className="text-sm text-muted">{aiSummary}</dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-3">
              <dt className="text-[15px] font-bold text-ink">HMRC</dt>
              <dd className="flex flex-wrap items-center gap-3">
                <span className="text-sm text-muted">Sandbox · not connected</span>
                {/* A real integration: its connect step lives on the VAT page (no disabled stand-in here). */}
                <Link
                  href="/vat"
                  className="inline-flex h-10 items-center whitespace-nowrap rounded-xl border-2 border-teal bg-white px-4 text-sm font-bold text-teal-dark"
                >
                  Connect on the VAT page
                </Link>
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="settings-audit" className={card}>
          <h2 id="settings-audit" className={heading}>
            Audit log
          </h2>
          <p className="mt-1 text-sm text-muted">Every action in your books, by you or an agent. Read-only.</p>
          <Link href="/audit" className="mt-2 inline-block text-sm font-bold text-teal-dark">
            Open the audit trail
          </Link>
        </section>

        <section aria-labelledby="settings-disconnect" className={card}>
          <h2 id="settings-disconnect" className={heading}>
            Disconnect
          </h2>
          <p className="mt-1 text-sm text-muted">
            Your files stay in your OneDrive. We remove this device&apos;s sign-in and settings.
          </p>
          <button
            type="button"
            onClick={disconnect}
            className="mt-3 h-12 rounded-xl border-2 border-teal bg-white px-5 text-[15px] font-extrabold text-teal-dark"
          >
            Disconnect Accnomos
          </button>
          {disconnected && (
            <p role="status" className="mt-2 text-sm font-bold text-teal-dark">
              Disconnected.
            </p>
          )}
        </section>
      </div>

      <div
        role="tabpanel"
        id="panel-ai"
        aria-labelledby="tab-ai"
        hidden={group !== "ai"}
        className="mt-4 space-y-4"
      >
        <section aria-labelledby="settings-ai" className={card}>
          <h2 id="settings-ai" className={heading}>
            AI
          </h2>
          <p className="mt-1 text-sm text-muted">
            How Accnomos answers your questions and reads your documents. The address or key never
            leaves this device.
          </p>
          <ChooseAi />
          <p className="mt-3 text-sm text-muted">
            Without a choice here, the server&apos;s own Meta models answer, trying each in turn if one is down.{" "}
            <Link href="/models" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
              See the Meta models at work
            </Link>
          </p>
        </section>

        <section aria-labelledby="settings-verifier" className={card}>
          <h2 id="settings-verifier" className={heading}>
            Second reading (verifier)
          </h2>
          <p className="mt-1 text-sm text-muted">
            Every extraction that passes the code checks is read again by a second model with a
            different prompt that never sees the first answer. Code compares six fields: when all
            agree, the Review card says so; any disagreement sends the proposal to Needs a look
            showing both values. If the second reading cannot run, the proposal waits for you —
            that is the safety design, not a pass.
          </p>
        </section>
      </div>

      <div
        role="tabpanel"
        id="panel-automation"
        aria-labelledby="tab-automation"
        hidden={group !== "automation"}
        className="mt-4 space-y-4"
      >
        <section aria-labelledby="settings-autopilot" className={card}>
          <h2 id="settings-autopilot" className={heading}>
            Autopilot level
          </h2>
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

        <OutlookIntake card={card} heading={heading} />

        <EmailIntake card={card} heading={heading} />

        <section id="automation" aria-labelledby="settings-automation" className={card}>
          <h2 id="settings-automation" className={heading}>
            Inbox triage
          </h2>
          <div className="mt-1 divide-y divide-border">
            <InboxTriageSetting />
          </div>
        </section>

        <WorkingHours card={card} heading={heading} />
      </div>

      <div
        role="tabpanel"
        id="panel-business"
        aria-labelledby="tab-business"
        hidden={group !== "business"}
        className="mt-4 space-y-4"
      >
        <ProfileDetails card={card} heading={heading} />

        <BusinessDetails card={card} heading={heading} />

        <div id="settings-invoice-profile" className="scroll-mt-4">
          <InvoiceProfileForm card={card} heading={heading} />
        </div>

        <OnlinePayments card={card} heading={heading} />

        <VatPeriodSettings card={card} heading={heading} />

        <SelfEmployedSetting card={card} heading={heading} />
        <VatSchemeSettings card={card} heading={heading} />

        <StaffEditor card={card} heading={heading} />

        <PersonalFinanceSetting card={card} heading={heading} />

        <LandlordSetting card={card} heading={heading} />
      </div>

      <div
        role="tabpanel"
        id="panel-accountant"
        aria-labelledby="tab-accountant"
        hidden={group !== "accountant"}
        className="mt-4 space-y-4"
      >
        {group === "accountant" && <YourAccountant card={card} heading={heading} />}
      </div>

      <div
        role="tabpanel"
        id="panel-files"
        aria-labelledby="tab-files"
        hidden={group !== "files"}
        className="mt-4 space-y-4"
      >
        {group === "files" && <FilesBackups card={card} heading={heading} />}
      </div>

      <div
        role="tabpanel"
        id="panel-data"
        aria-labelledby="tab-data"
        hidden={group !== "data"}
        className="mt-4 space-y-4"
      >
        <YourData card={card} heading={heading} />
      </div>
    </div>
  );
}
