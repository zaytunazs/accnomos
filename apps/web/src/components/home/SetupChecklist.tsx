"use client";

import { useUkBooks } from "@/lib/region";
import { isDemo } from "@/lib/demo";
import Link from "next/link";
import { useEffect, useState } from "react";
import { aiTested, loadAiConfig, RUNTIME_URL } from "@/lib/ai-config";
import { loadBusiness, validateVatNumber } from "@/lib/business";
import { currentMeta, PROFILE_EVENT } from "@/lib/profiles";
import { runtime, runtimeHeaders } from "@/lib/runtime";
import { useHome } from "./HomeData";

const DISMISS_KEY = "accnomos.setup.dismissed";
const TRIED_KEY = "accnomos.setup.tried-receipt";
export const CONTACTS_IMPORTED_KEY = "accnomos.setup.contacts-imported";

/** Remember the sample receipt was tried, so the step stays ticked. */
export function markReceiptTried(): void {
  try {
    window.localStorage.setItem(TRIED_KEY, "1");
  } catch {
    /* storage unavailable — the step shows as unticked next visit */
  }
}

/** Remember that the Outlook contacts import ran once, so the optional step stays ticked. */
export function markContactsImported(): void {
  try {
    window.localStorage.setItem(CONTACTS_IMPORTED_KEY, "1");
  } catch {
    /* storage unavailable — the step shows as unticked next visit */
  }
}

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    /* storage unavailable — the step shows as unticked next visit */
  }
}

/** Personal books: what the household steps need, each read from the books (null while it is being read). */
interface HouseholdFacts {
  statement: boolean | null; // a bank statement imported (GET /books/bank/statements)
  budgets: boolean | null; // a monthly budget saved (GET /personal/budgets)
  goal: boolean | null; // a goal set (GET /books/goals, code only: no model call for a tick)
}

async function hasGoal(account: Parameters<typeof runtimeHeaders>[0]): Promise<boolean> {
  const res = await fetch(`${RUNTIME_URL}/books/goals?note_ai=false`, { headers: await runtimeHeaders(account) });
  if (!res.ok) throw new Error(String(res.status));
  return ((await res.json()) as { goals: unknown[] }).goals.length > 0;
}

interface Step {
  id: string;
  label: string;
  hint: string;
  href: string;
  done: boolean;
  optional?: boolean;
}

/** Where a step's link goes, for its accessible name ("Set up in Budget"). */
function placeOf(href: string): string {
  if (href.startsWith("/settings")) return "Settings";
  if (href.startsWith("/connect")) return "Connect";
  if (href.startsWith("/bank")) return "Bank";
  if (href.startsWith("/personal")) return "Budget";
  if (href.startsWith("/goals")) return "Goals";
  return "Review";
}

function Tick({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${
        done ? "bg-teal text-white" : "border-2 border-border bg-white text-muted"
      }`}
    >
      {done ? "✓" : "·"}
    </span>
  );
}

/**
 * First-run checklist on Home. Signed in only, and only while a required step is still open:
 * hide when every required step is done, or once dismissed (remembered on this device).
 * Local steps read the existing settings; the invoice profile is the one GET /invoices/profile.
 * Personal books (profile kind "personal") get household steps instead of the business ones (business name, VAT,
 * the business details wizard, invoice profile, Outlook customers and suppliers): import a bank statement, set
 * monthly budgets, set a goal, each ticked from what the books hold.
 */
export default function SetupChecklist() {
  const home = useHome();
  const account = home.mode === "live" || home.mode === "loading" || home.mode === "error" ? home.account : null;
  const [dismissed, setDismissed] = useState(true); // hidden until localStorage says otherwise
  const [triedReceipt, setTriedReceipt] = useState(false);
  const [contactsImported, setContactsImported] = useState(false);
  const [local, setLocal] = useState<{ ai: boolean; business: boolean; vat: boolean } | null>(null);
  const [profileDone, setProfileDone] = useState<boolean | null>(null);
  const [wizardDone, setWizardDone] = useState<boolean | null>(null);
  const [household, setHousehold] = useState<HouseholdFacts | null>(null);
  const uk = useUkBooks();
  const [personal, setPersonal] = useState(false); // the current profile's books are personal (lib/profiles.ts)

  useEffect(() => {
    const read = () => setPersonal(currentMeta()?.kind === "personal");
    queueMicrotask(read);
    window.addEventListener(PROFILE_EVENT, read);
    return () => window.removeEventListener(PROFILE_EVENT, read);
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      setDismissed(readFlag(DISMISS_KEY));
      setTriedReceipt(readFlag(TRIED_KEY));
      setContactsImported(readFlag(CONTACTS_IMPORTED_KEY));
      const business = loadBusiness();
      const vrn = (business?.vatNumber ?? "").trim();
      setLocal({
        ai: aiTested(loadAiConfig()),
        business:
          business !== null &&
          business.name.trim() !== "" &&
          (business.vatRegistered === false || vrn === "" || validateVatNumber(vrn) === null),
        vat: business !== null,
      });
      if (!account) setProfileDone(false);
    });
    if (account && personal) {
      queueMicrotask(() => setHousehold({ statement: null, budgets: null, goal: null }));
      const set = (k: keyof HouseholdFacts) => (v: boolean) => setHousehold((h) => ({ ...(h ?? { statement: null, budgets: null, goal: null }), [k]: v }));
      runtime.bank.statements(account).then((all) => all.length > 0, () => false).then(set("statement"));
      runtime.personal.budgets(account).then((b) => Object.values(b).some((v) => v > 0), () => false).then(set("budgets"));
      hasGoal(account).catch(() => false).then(set("goal"));
      return;
    }
    queueMicrotask(() => setHousehold(null));
    if (account) {
      runtime
        .invoiceProfile(account)
        .then((p) => setProfileDone(p.name.trim() !== "" && p.address.trim() !== ""))
        .catch(() => setProfileDone(false));
      runtime.setupWizard
        .status(account)
        .then((s) => setWizardDone(!!(s.setup as Record<string, unknown>).confirmed_at))
        .catch(() => setWizardDone(null));
    } else {
      // Defer to avoid a synchronous setState in the effect body.
      queueMicrotask(() => setWizardDone(null));
    }
  }, [account, personal]);

  if (!account || dismissed || local === null || isDemo()) return null; // a demo's books are already set up

  const checking = "Checking your OneDrive…";
  const allSteps: Step[] = household
    ? [
        {
          id: "onedrive",
          label: "Connect OneDrive",
          hint: "Signed in — your money records live in your own folder",
          href: "/connect",
          done: true,
        },
        {
          id: "ai",
          label: "Choose your AI",
          hint: "A local address or a key, tested and answering",
          href: "/connect/ai",
          done: local.ai,
        },
        {
          id: "statement",
          label: "Import a bank statement",
          hint: household.statement === null ? checking : "A CSV from your bank: money in and out, sorted into categories",
          href: "/bank",
          done: household.statement === true,
        },
        {
          id: "budgets",
          label: "Set your monthly budgets",
          hint: household.budgets === null ? checking : "How much for groceries, eating out, bills and the rest",
          href: "/personal",
          done: household.budgets === true,
        },
        {
          id: "goal",
          label: "Set a goal",
          hint: household.goal === null ? checking : "Save for something, or spend less on something",
          href: "/goals",
          done: household.goal === true,
        },
        {
          id: "receipt",
          label: "Try a receipt",
          hint: "Add the sample receipt and approve the reading",
          href: "/connect/ready",
          done: triedReceipt,
        },
      ]
    : [
    {
      id: "onedrive",
      label: "Connect OneDrive",
      hint: "Signed in — your books live in your own folder",
      href: "/connect",
      done: true,
    },
    {
      id: "ai",
      label: "Choose your AI",
      hint: "A local address or a key, tested and answering",
      href: "/connect/ai",
      done: local.ai,
    },
    {
      id: "business",
      label: "Business name + VAT number",
      hint: "Who the books belong to",
      href: "/connect/business",
      done: local.business,
    },
    {
      id: "vat",
      label: "VAT period",
      hint: "Quarterly stagger or start month",
      href: "/connect/business",
      done: local.vat,
    },
    {
      id: "wizard",
      label: "Business details wizard",
      hint: wizardDone === null ? "Checking your OneDrive…" : "Type, VAT, Income Tax, CIS, payroll, property",
      href: "/setup",
      done: wizardDone === true,
    },
    {
      id: "invoice",
      label: "Invoice profile",
      hint: profileDone === null ? "Checking your OneDrive…" : "Logo, address and payment terms",
      href: "/settings#settings-invoice-profile",
      done: profileDone === true,
    },
    {
      id: "contacts",
      label: "Import Outlook contacts",
      hint: "Optional — customers and suppliers from your mail",
      href: "/settings#settings-intake",
      done: contactsImported,
      optional: true,
    },
    {
      id: "receipt",
      label: "Try a receipt",
      hint: "Add the sample receipt and approve the reading",
      href: "/connect/ready",
      done: triedReceipt,
    },
      ];
  // Books kept outside the UK: no VAT period or HMRC wizard; the business step asks the country and tax instead.
  const steps = uk
    ? allSteps
    : allSteps
        .filter((st) => st.id !== "vat" && st.id !== "wizard")
        .map((st) => (st.id === "business" ? { ...st, label: "Business name, country and tax" } : st));
  const requiredOpen = steps.some((s) => !s.optional && !s.done);
  if (!requiredOpen) return null;

  function dismiss() {
    writeFlag(DISMISS_KEY);
    setDismissed(true);
  }

  return (
    <section
      aria-labelledby="setup-checklist"
      className="rounded-2xl border border-border bg-white p-4 sm:p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="setup-checklist" className="text-[17px] font-bold text-ink">
            Get set up
          </h2>
          <p className="mt-0.5 text-sm text-muted">
            {steps.filter((s) => s.done).length} of {steps.length} done — each step takes a minute.
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-bold text-muted hover:bg-ground hover:text-ink"
        >
          Dismiss
        </button>
      </div>
      <ul className="mt-3 divide-y divide-border">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-3 py-2.5">
            <Tick done={s.done} />
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-bold text-ink">
                {s.label}
                {s.optional && <span className="ml-2 text-[13px] font-semibold text-muted">Optional</span>}
                {s.done && (
                  <span className="sr-only"> (done)</span>
                )}
              </p>
              <p className="text-[13px] text-muted">{s.hint}</p>
            </div>
            <Link
              href={s.href}
              aria-label={`${s.label} — ${s.done ? "review" : s.id === "receipt" ? "try it" : "set up"} in ${placeOf(s.href)}`}
              onClick={
                s.id === "receipt"
                  ? () => {
                      writeFlag(TRIED_KEY);
                      setTriedReceipt(true);
                    }
                  : undefined
              }
              className={`shrink-0 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-bold ${
                s.done ? "text-teal-dark hover:bg-ground" : "bg-teal text-white hover:bg-teal-dark"
              }`}
            >
              {s.done ? "Review" : s.id === "receipt" ? "Try it" : "Set up"}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
