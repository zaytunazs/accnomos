"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAccount } from "@/components/jobs/useAccount";
import { landlordOn, property, setLandlordOn } from "@/lib/property";

/**
 * Settings › Business › I let property: adds the Property page to the menu. Off by default. Saved in the books
 * (_System/Property/settings.json) when signed in, and mirrored on this device so the menu needs no call.
 */
export default function LandlordSetting({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [on, setOn] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    queueMicrotask(() => setOn(landlordOn()));
  }, []);
  useEffect(() => {
    if (!account) return;
    let stale = false;
    property.settings(account).then(
      (s) => {
        if (stale) return;
        setOn(s.landlord_mode);
        setLandlordOn(s.landlord_mode);
      },
      () => undefined, // keep this device's choice
    );
    return () => {
      stale = true;
    };
  }, [account]);

  async function toggle() {
    const next = !on;
    setLandlordOn(next);
    setOn(next);
    setNote(null);
    if (!account) return;
    try {
      const s = await property.settings(account);
      await property.saveSettings(account, { ...s, landlord_mode: next });
    } catch (e) {
      setNote(`Saved on this device only: ${(e as Error).message}`);
    }
  }

  return (
    <section aria-labelledby="settings-landlord" className={card}>
      <h2 id="settings-landlord" className={heading}>
        Property income
      </h2>
      <p className="mt-1 text-sm text-muted">
        For landlords with a home, a flat or a room to let: rent and costs per property, shares for joint owners, and the Making Tax Digital
        quarterly updates for UK property.
      </p>
      <label className="mt-3 flex min-h-11 items-center gap-3 text-[15px] font-bold text-ink">
        <input type="checkbox" checked={on} onChange={toggle} className="h-5 w-5 accent-teal" />
        I let property (landlord mode)
      </label>
      {note && <p className="mt-1 text-sm text-muted">{note}</p>}
      {on && (
        <Link href="/property" className="mt-2 inline-block text-sm font-bold text-teal-dark">
          Open Property
        </Link>
      )}
    </section>
  );
}
