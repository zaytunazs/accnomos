"use client";

import { useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { KIND_LABEL, linkedAccounts, profileMeta, rememberProfile, startAdding } from "@/lib/profiles";
import { runtime, type RtLinkedAccount, type RtProfile, type RtProfileKind, type RtProfileSettings } from "@/lib/runtime";

const input = "mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px] text-ink";
const label = "text-xs font-bold text-muted";

const KINDS: { value: RtProfileKind; hint: string }[] = [
  { value: "company", hint: "A limited company, with its own company number" },
  { value: "sole_trader", hint: "Self-employment, reported on your Self Assessment" },
  { value: "personal", hint: "Household money: no VAT, invoices or payroll" },
];

/**
 * Settings › Business › Profile: what these books are (services/runtime/app/profile.py), saved in this account's own
 * OneDrive as `_System/profile.json`. The kind decides which pages show (lib/profiles.ts, AppNav).
 */
export default function ProfileDetails({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const router = useRouter();
  const [profile, setProfile] = useState<RtProfile | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<RtProfileKind>("company");
  const [settings, setSettings] = useState<RtProfileSettings>({});
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [here, setHere] = useState<string[]>([]); // sign-ins this browser holds
  const ids = useId();

  useEffect(() => {
    linkedAccounts().then(
      ({ all }) => setHere(all.map((a) => a.username.toLowerCase())),
      () => setHere([]),
    );
  }, []);

  useEffect(() => {
    if (!account) return;
    runtime.profile(account).then(
      (p) => {
        setProfile(p);
        setName(p.exists ? p.name : "");
        setKind(p.kind);
        setSettings(p.settings);
        rememberProfile(account.homeAccountId, p);
      },
      (e) => setStatus({ ok: false, text: errorText(e) }),
    );
  }, [account]);

  if (!account) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!account) return;
    setSaving(true);
    setStatus(null);
    const { active, all } = await linkedAccounts();
    const linked: RtLinkedAccount[] = all
      .filter((a) => a.homeAccountId !== active?.homeAccountId)
      .map((a) => {
        const m = profileMeta(a.homeAccountId);
        return { username: a.username, name: m?.exists ? m.name : "", kind: m?.exists ? m.kind : null };
      });
    const body: RtProfileSettings =
      kind === "personal"
        ? {}
        : kind === "company"
          ? { company_number: settings.company_number || null, vat_number: settings.vat_number || null, vat_registered: !!settings.vat_registered }
          : {
              utr: settings.utr || null,
              accounting_period_start: settings.accounting_period_start || "04-06",
              vat_number: settings.vat_number || null,
              vat_registered: !!settings.vat_registered,
            };
    try {
      const p = await runtime.saveProfile(account, { name, kind, settings: body, linked });
      setProfile(p);
      setSettings(p.settings);
      rememberProfile(account.homeAccountId, p);
      setStatus({ ok: true, text: "Saved to your OneDrive." });
    } catch (err) {
      setStatus({ ok: false, text: errorText(err) });
    } finally {
      setSaving(false);
    }
  }

  const set = (change: Partial<RtProfileSettings>) => setSettings((s) => ({ ...s, ...change }));
  const elsewhere = (profile?.linked ?? []).filter((l) => !here.includes(l.username.toLowerCase()));

  return (
    <section id="profile" aria-labelledby="settings-profile" className={`${card} scroll-mt-4`}>
      <h2 id="settings-profile" className={heading}>
        Profile
      </h2>
      <p className="mt-1 text-sm text-muted">
        What the books in {account.username}&apos;s OneDrive are. Each company, sole-trader business or set of personal
        finances is its own Microsoft account; switch between them from the menu at the top.
      </p>
      {!profile && !status && <p className="mt-3 text-sm text-muted">Reading your profile…</p>}
      {profile && (
        <form onSubmit={save} className="mt-3 space-y-3">
          <div>
            <label className={label} htmlFor={`${ids}-name`}>
              Profile name
            </label>
            <input
              id={`${ids}-name`}
              className={input}
              required
              maxLength={80}
              value={name}
              placeholder="e.g. Sam Builds Ltd"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <fieldset>
            <legend className={label}>Kind of books</legend>
            <div className="mt-1 grid gap-2">
              {KINDS.map((k) => (
                <label key={k.value} className="flex min-h-11 items-start gap-3 rounded-xl border border-border px-3 py-2">
                  <input
                    type="radio"
                    name={`${ids}-kind`}
                    value={k.value}
                    checked={kind === k.value}
                    onChange={() => setKind(k.value)}
                    className="mt-1"
                  />
                  <span>
                    <span className="block text-[15px] font-semibold text-ink">{KIND_LABEL[k.value]}</span>
                    <span className="block text-xs text-muted">{k.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          {kind === "company" && (
            <div>
              <label className={label} htmlFor={`${ids}-crn`}>
                Company number (optional)
              </label>
              <input
                id={`${ids}-crn`}
                className={input}
                inputMode="text"
                value={settings.company_number ?? ""}
                onChange={(e) => set({ company_number: e.target.value })}
              />
            </div>
          )}
          {kind === "sole_trader" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className={label} htmlFor={`${ids}-utr`}>
                  UTR (optional)
                </label>
                <input
                  id={`${ids}-utr`}
                  className={input}
                  inputMode="numeric"
                  value={settings.utr ?? ""}
                  onChange={(e) => set({ utr: e.target.value })}
                />
              </div>
              <div>
                <label className={label} htmlFor={`${ids}-start`}>
                  Accounting year starts (MM-DD)
                </label>
                <input
                  id={`${ids}-start`}
                  className={input}
                  inputMode="numeric"
                  pattern="(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
                  value={settings.accounting_period_start ?? "04-06"}
                  onChange={(e) => set({ accounting_period_start: e.target.value })}
                />
              </div>
            </div>
          )}
          {kind !== "personal" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex min-h-11 items-center gap-3 text-[15px] font-semibold text-ink">
                <input
                  type="checkbox"
                  checked={!!settings.vat_registered}
                  onChange={(e) => set({ vat_registered: e.target.checked })}
                />
                VAT-registered
              </label>
              <div>
                <label className={label} htmlFor={`${ids}-vrn`}>
                  VAT number (optional)
                </label>
                <input
                  id={`${ids}-vrn`}
                  className={input}
                  value={settings.vat_number ?? ""}
                  onChange={(e) => set({ vat_number: e.target.value })}
                />
              </div>
            </div>
          )}
          <button type="submit" disabled={saving} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white">
            {saving ? "Saving…" : "Save profile"}
          </button>
        </form>
      )}
      {status && (
        <p role={status.ok ? "status" : "alert"} className={`mt-2 text-sm ${status.ok ? "text-teal-dark" : "text-warn-ink"}`}>
          {status.text}
        </p>
      )}
      {elsewhere.length > 0 && (
        <div className="mt-3 rounded-xl bg-ground p-3 text-sm text-ink">
          <p>Linked to this profile on another device:</p>
          <ul className="mt-1 list-disc pl-5">
            {elsewhere.map((l) => (
              <li key={l.username}>
                {l.name ? `${l.name} (${l.username})` : l.username}
                {l.kind ? `, ${KIND_LABEL[l.kind].toLowerCase()}` : ""}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => {
              startAdding(account.homeAccountId);
              router.push("/connect?add=1");
            }}
            className="mt-2 min-h-11 font-bold text-teal-dark"
          >
            Add another account / business
          </button>
        </div>
      )}
    </section>
  );
}
