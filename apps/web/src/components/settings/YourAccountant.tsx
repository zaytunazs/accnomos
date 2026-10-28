"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, useAccount } from "@/components/jobs/useAccount";
import { RuntimeErrorNote } from "@/components/States";
import QueryThreads from "@/components/accountant/QueryThreads";
import { KIND_LABELS, type ClientAccess, type ClientKind, type RtAccountantSettings, type RtClientProfile, type RtInvitation } from "@/lib/accountant";
import { loadBusiness, MONTH_NAMES } from "@/lib/business";
import { isPersonalAccount } from "@/lib/msal";
import { accountantApi } from "@/lib/runtime";

const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/London" });

/** The profile the portal shows, first filled in from this device's business details (Settings › Business). */
function profileFromBusiness(): RtClientProfile {
  const b = loadBusiness();
  return {
    name: b?.name ?? "",
    kind: "business",
    vat_registered: b?.vatRegistered ?? true,
    vat_start_month: b ? (b.stagger === "custom" ? b.customStartMonth : Number(b.stagger)) : 1,
    vat_months: b?.vatPeriod === "monthly" ? 1 : 3,
  };
}

function RoleChoice({ name, value, onChange, legend }: { name: string; value: ClientAccess; onChange: (v: ClientAccess) => void; legend: string }) {
  return (
    <fieldset className="mt-2">
      <legend className="text-sm font-semibold text-ink">{legend}</legend>
      <div className="mt-1 flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" name={name} checked={value === "read"} onChange={() => onChange("read")} /> View only (and leave queries)
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name={name} checked={value === "edit"} onChange={() => onChange("edit")} /> View and edit
        </label>
      </div>
    </fieldset>
  );
}

/** Settings › Your accountant: invite one, opt in to Accnomos accountants, see and answer queries. */
export default function YourAccountant({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  const [s, setS] = useState<RtAccountantSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<RtClientProfile | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<ClientAccess>("read");
  const [manual, setManual] = useState(false);
  const [message, setMessage] = useState("");
  const [teamRole, setTeamRole] = useState<ClientAccess>("read");
  const [agree, setAgree] = useState(false);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const got = await accountantApi.settings(account);
      setS(got);
      setProfile((p) => p ?? got.profile ?? profileFromBusiness());
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function run(what: () => Promise<unknown>, done: string) {
    setBusy(true);
    setStatus("");
    try {
      await what();
      setStatus(done);
      await load();
    } catch (e) {
      setStatus(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (account === undefined) return null;
  if (account === null) {
    return (
      <section aria-labelledby="settings-accountant" className={card}>
        <h2 id="settings-accountant" className={heading}>Your accountant</h2>
        <p className="mt-1 text-sm text-muted">Sign in to share your books with your accountant.</p>
      </section>
    );
  }

  const active = (s?.invitations ?? []).filter((i) => !i.revoked_at);
  const own = active.filter((i) => i.kind === "own");
  const team = active.find((i) => i.kind === "team");
  const personal = isPersonalAccount(account);

  return (
    <>
      <section aria-labelledby="settings-accountant" className={card}>
        <h2 id="settings-accountant" className={heading}>Your accountant</h2>
        <p className="mt-1 text-sm text-muted">
          Accnomos has no database of users: your accountant gets access because your Accnomos folder in OneDrive is
          shared with their Microsoft account. They sign in to the Accountant portal and open your books there. Removing
          access stops the sharing at once.
        </p>
        {error && <RuntimeErrorNote message={error} />}
        <p role="status" className="mt-2 min-h-5 text-sm text-ink">{status}</p>

        {own.length > 0 && (
          <ul aria-label="People with access" className="mt-2 divide-y divide-border">
            {own.map((i: RtInvitation) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>
                  <strong>{i.name || i.email}</strong>
                  {i.name ? ` (${i.email})` : ""} · {i.role === "edit" ? "View and edit" : "View only"} · since {day(i.invited_at)}
                  {i.method === "manual" ? " · shared by you in OneDrive" : ""}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => accountantApi.revoke(account, i.id),
                      i.method === "manual"
                        ? `Recorded. You shared this in OneDrive yourself: remove ${i.email} there too (Manage access on the Accnomos folder).`
                        : `${i.email} no longer has access.`,
                    )
                  }
                  className="h-10 rounded-xl border-2 border-teal bg-white px-3 font-bold text-teal-dark disabled:opacity-60"
                >
                  Remove access
                </button>
              </li>
            ))}
          </ul>
        )}

        <form
          aria-label="Invite your accountant"
          className="mt-3 space-y-2 rounded-xl bg-ground p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void run(
              () => accountantApi.invite(account, { email, name, role, method: manual ? "manual" : "graph", message }),
              manual ? `Recorded that you shared your books with ${email}.` : `Invited ${email}. Microsoft emails them a link.`,
            ).then(() => {
              setEmail("");
              setName("");
              setMessage("");
            });
          }}
        >
          <h3 className="text-[15px] font-bold text-ink">Invite your accountant</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-sm font-semibold text-ink">
              Their email (Microsoft account)
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]" />
            </label>
            <label className="text-sm font-semibold text-ink">
              Name (optional)
              <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]" />
            </label>
          </div>
          <RoleChoice name="invite-role" legend="What they can do" value={role} onChange={setRole} />
          <label className="flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} className="mt-1" />
            <span>I shared the Accnomos folder with them myself in OneDrive (just record it here)</span>
          </label>
          {!manual && (
            <label className="block text-sm font-semibold text-ink">
              Message (optional, goes in Microsoft&apos;s invitation email)
              <textarea value={message} maxLength={1000} rows={2} onChange={(e) => setMessage(e.target.value)} className="mt-1 w-full rounded-xl border border-border bg-white p-2 text-[15px]" />
            </label>
          )}
          {!manual && personal && (
            <p className="text-[13px] text-muted">
              With a personal Microsoft account, Microsoft asks you once for permission to share files (“Files.ReadWrite”,
              which covers your whole OneDrive). Accnomos uses it only to share and unshare the Accnomos folder. If you
              would rather not, share the folder yourself in OneDrive and tick the box above.
            </p>
          )}
          <button type="submit" disabled={busy || !email.trim()} className="h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60">
            {manual ? "Record access" : "Invite"}
          </button>
        </form>
        {s?.client_code && (
          <p className="mt-2 text-[13px] text-muted">
            Client code for your accountant&apos;s portal: <code className="font-mono text-ink">{s.client_code}</code>
          </p>
        )}
      </section>

      {profile && (
        <section aria-labelledby="settings-accountant-profile" className={card}>
          <h2 id="settings-accountant-profile" className={heading}>What your accountant sees about you</h2>
          <p className="mt-1 text-sm text-muted">Shown in their portal next to your books. Saved in _System/accountant.json in your OneDrive.</p>
          <form
            className="mt-2 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => accountantApi.saveProfile(account, profile), "Saved.");
            }}
          >
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-sm font-semibold text-ink">
                Name
                <input value={profile.name} maxLength={120} onChange={(e) => setProfile({ ...profile, name: e.target.value })} className="mt-1 h-11 w-full rounded-xl border border-border px-3 text-[15px]" />
              </label>
              <label className="text-sm font-semibold text-ink">
                These books are for
                <select value={profile.kind} onChange={(e) => setProfile({ ...profile, kind: e.target.value as ClientKind })} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]">
                  {(Object.keys(KIND_LABELS) as ClientKind[]).map((k) => (
                    <option key={k} value={k}>{KIND_LABELS[k]}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={profile.vat_registered} onChange={(e) => setProfile({ ...profile, vat_registered: e.target.checked })} /> VAT-registered
            </label>
            {profile.vat_registered && (
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-sm font-semibold text-ink">
                  A VAT period starts in
                  <select value={profile.vat_start_month} onChange={(e) => setProfile({ ...profile, vat_start_month: Number(e.target.value) })} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]">
                    {MONTH_NAMES.map((m, i) => (
                      <option key={m} value={i + 1}>{m}</option>
                    ))}
                  </select>
                </label>
                <label className="text-sm font-semibold text-ink">
                  Returns
                  <select value={profile.vat_months} onChange={(e) => setProfile({ ...profile, vat_months: Number(e.target.value) as 1 | 3 })} className="mt-1 h-11 w-full rounded-xl border border-border bg-white px-3 text-[15px]">
                    <option value={3}>Quarterly</option>
                    <option value={1}>Monthly</option>
                  </select>
                </label>
              </div>
            )}
            <button type="submit" disabled={busy} className="h-11 rounded-xl border-2 border-teal bg-white px-5 text-[15px] font-bold text-teal-dark disabled:opacity-60">
              Save details
            </button>
          </form>
        </section>
      )}

      {s?.team_available && (
        <section aria-labelledby="settings-accountant-team" className={card}>
          <h2 id="settings-accountant-team" className={heading}>Reviews by Accnomos accountants</h2>
          {team ? (
            <>
              <p className="mt-1 text-sm text-ink">
                On since {day(team.invited_at)} ({team.role === "edit" ? "view and edit" : "view only"}), shared with {team.email}.
                You agreed to the text of {team.consent?.version}.
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => accountantApi.teamOptOut(account), "Reviews stopped: the sharing has been removed.")}
                className="mt-2 h-11 rounded-xl border-2 border-teal bg-white px-5 text-[15px] font-bold text-teal-dark disabled:opacity-60"
              >
                Stop reviews
              </button>
            </>
          ) : (
            <form
              className="mt-1"
              onSubmit={(e) => {
                e.preventDefault();
                void run(
                  () => accountantApi.teamOptIn(account, { agree, consent_version: s.consent_version, role: teamRole }),
                  "You opted in. Accnomos accountants can now see your books.",
                ).then(() => setAgree(false));
              }}
            >
              <p className="text-sm text-muted">Optional and separate from inviting your own accountant. Please read all of this first:</p>
              <ul aria-label="What opting in means" className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink">
                {s.consent_text.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <RoleChoice name="team-role" legend="What they can do" value={teamRole} onChange={setTeamRole} />
              <label className="mt-2 flex items-start gap-2 text-sm text-ink">
                <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-1" />
                <span>I have read this and agree to share my books with Accnomos accountants</span>
              </label>
              <button type="submit" disabled={busy || !agree} className="mt-2 h-11 rounded-xl bg-teal px-5 text-[15px] font-extrabold text-white disabled:opacity-60">
                Opt in to reviews
              </button>
            </form>
          )}
        </section>
      )}

      <QueryThreads account={account} me="client" canAsk={false} heading="Queries from your accountant" />
    </>
  );
}
