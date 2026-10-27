"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { aiTested, loadAiConfig } from "@/lib/ai-config";
import { loadBusiness, validateVatNumber } from "@/lib/business";
import { runtime } from "@/lib/runtime";
import { useHome } from "./HomeData";

const DISMISS_KEY = "accnomos.setup.dismissed";
const TRIED_KEY = "accnomos.setup.tried-receipt";
export const CONTACTS_IMPORTED_KEY = "accnomos.setup.contacts-imported";

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

interface Step {
  id: string;
  label: string;
  hint: string;
  href: string;
  done: boolean;
  optional?: boolean;
}

function Tick({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[13px] font-extrabold ${
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
 */
export default function SetupChecklist() {
  const home = useHome();
  const account = home.mode === "live" || home.mode === "loading" || home.mode === "error" ? home.account : null;
  const [dismissed, setDismissed] = useState(true); // hidden until localStorage says otherwise
  const [triedReceipt, setTriedReceipt] = useState(false);
  const [contactsImported, setContactsImported] = useState(false);
  const [local, setLocal] = useState<{ ai: boolean; business: boolean; vat: boolean } | null>(null);
  const [profileDone, setProfileDone] = useState<boolean | null>(null);

  useEffect(() => {
    queueMicrotask(() => {
      setDismissed(readFlag(DISMISS_KEY));
      setTriedReceipt(readFlag(TRIED_KEY));
      setContactsImported(readFlag(CONTACTS_IMPORTED_KEY));
      const business = loadBusiness();
      setLocal({
        ai: aiTested(loadAiConfig()),
        business:
          business !== null && business.name.trim() !== "" && validateVatNumber(business.vatNumber) === null,
        vat: business !== null,
      });
      if (!account) setProfileDone(false);
    });
    if (account) {
      runtime
        .invoiceProfile(account)
        .then((p) => setProfileDone(p.name.trim() !== "" && p.address.trim() !== ""))
        .catch(() => setProfileDone(false));
    }
  }, [account]);

  if (!account || dismissed || local === null) return null;

  const steps: Step[] = [
    {
      id: "onedrive",
      label: "Connect OneDrive",
      hint: "Signed in — your books live in your own folder",
      href: "/settings#settings-connections",
      done: true,
    },
    {
      id: "ai",
      label: "Choose your AI",
      hint: "A local address or a key, tested and answering",
      href: "/settings#settings-ai",
      done: local.ai,
    },
    {
      id: "business",
      label: "Business name + VAT number",
      hint: "Who the books belong to",
      href: "/settings#settings-business",
      done: local.business,
    },
    {
      id: "vat",
      label: "VAT period",
      hint: "Quarterly stagger or start month",
      href: "/settings#settings-vat-periods",
      done: local.vat,
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
      hint: "Add one on Review and approve the reading",
      href: "/review",
      done: triedReceipt,
    },
  ];
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
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="setup-checklist" className="text-[17px] font-extrabold text-ink">
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
              aria-label={`${s.label} — ${s.done ? "review" : "set up"} in ${s.href.startsWith("/settings") ? "Settings" : "Review"}`}
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
