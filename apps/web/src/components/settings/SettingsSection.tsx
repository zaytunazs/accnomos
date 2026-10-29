"use client";

import Link from "next/link";
import InvoiceProfileForm from "@/components/invoices/InvoiceProfileForm";
import OnlinePayments from "@/components/settings/OnlinePayments";
import StaffEditor from "@/components/settings/StaffEditor";
import VatPeriodSettings from "@/components/settings/VatPeriodSettings";
import VatSchemeSettings from "@/components/settings/VatSchemeSettings";

/** The look Settings uses for its cards (SettingsPanels.tsx). */
const card = "rounded-2xl border border-border bg-white p-4";
const heading = "text-[17px] font-extrabold text-ink";

/**
 * One group of settings on a page of its own, for the menu's Sales settings, Tax settings and Employees
 * (/settings/sales, /settings/tax, /settings/employees). The same forms as in Settings › Business.
 */
export default function SettingsSection({ part }: { part: "sales" | "tax" | "employees" }) {
  return (
    <div className="mt-4 space-y-4">
      {part === "sales" && (
        <>
          <InvoiceProfileForm card={card} heading={heading} />
          <OnlinePayments card={card} heading={heading} />
        </>
      )}
      {part === "tax" && (
        <>
          <VatPeriodSettings card={card} heading={heading} />
          <VatSchemeSettings card={card} heading={heading} />
        </>
      )}
      {part === "employees" && <StaffEditor card={card} heading={heading} />}
      <p className="text-sm text-muted">
        <Link href="/settings" className="font-bold text-teal-dark underline underline-offset-2">
          All settings
        </Link>
      </p>
    </div>
  );
}
