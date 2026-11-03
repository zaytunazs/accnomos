"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { gbp, runtime, ukDate, type RtBankLine, type RtPersonalCategory, type RtPersonalRule } from "@/lib/runtime";

/**
 * Budget › Categories and rules: the household's own categories, the rules that sort payments into them (first match
 * wins, so their order matters) and single bank lines put in a category by hand. The same things the Android app's
 * Categories and rules screen does (apps/mobile/lib/screens/household_rules_screen.dart), on the same routes
 * (services/runtime/app/routes_personal.py). Nothing here touches the business ledger or business bank rules.
 */

type Tab = "categories" | "rules" | "lines";
/** Run a change; the page shows `done` (or the server's refusal) in its one status line and reloads its figures. */
export type Act = <T>(key: string, fn: () => Promise<T>, done: string | ((r: T) => string)) => Promise<boolean>;

const OTHER = "other";
const PAGE = 100;
const input = "h-11 min-w-0 rounded-xl border border-border bg-white px-3 text-[15px]";
const button = "h-11 rounded-xl bg-teal px-5 text-[15px] font-bold text-white disabled:opacity-60";
const quiet = "h-11 rounded-xl border border-border bg-white px-4 text-[15px] font-bold disabled:opacity-60";
const link = "h-11 shrink-0 rounded-xl px-3 font-bold text-teal-dark disabled:opacity-60";
const pounds = (pence: number) => (pence < 0 ? `-${gbp(-pence / 100)}` : gbp(pence / 100));

export default function HouseholdRules({
  account,
  cats,
  rules,
  busy,
  act,
  uncategorised,
}: {
  account: AccountInfo;
  cats: RtPersonalCategory[];
  rules: RtPersonalRule[];
  busy: string | null;
  act: Act;
  uncategorised: number;
}) {
  const [tab, setTab] = useState<Tab>("categories");
  // /personal#household-lines (the Bank page's "Lines with no category") opens straight on the lines.
  useEffect(() => {
    if (window.location.hash === "#household-lines") {
      queueMicrotask(() => {
        setTab("lines");
        document.getElementById("categories-rules")?.scrollIntoView();
      });
    }
  }, []);
  const tabs: { id: Tab; label: string; count: number | null }[] = [
    { id: "categories", label: "Categories", count: cats.length },
    { id: "rules", label: "Rules", count: rules.length },
    { id: "lines", label: "Lines", count: uncategorised > 0 ? uncategorised : null },
  ];

  function onKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length].id;
    setTab(next);
    document.getElementById(`hh-tab-${next}`)?.focus();
  }

  return (
    <section id="categories-rules" aria-labelledby="p-rules" className="scroll-mt-24 rounded-2xl border border-border bg-white p-4 sm:p-5">
      <h2 id="p-rules" className="text-[19px] font-extrabold text-ink">
        Categories and rules
      </h2>
      <p className="mt-1 text-sm text-muted">
        Your household categories, the rules that sort payments into them (the first matching rule wins) and single lines you put in a
        category yourself. Separate from any business bank rules.
      </p>
      <div role="tablist" aria-label="Categories and rules" className="mt-3 flex flex-wrap gap-2 border-b border-border pb-3">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`hh-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`hh-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`flex h-11 items-center gap-2 rounded-xl px-4 text-[15px] font-semibold ${
              tab === t.id ? "bg-teal-tint text-teal-dark" : "text-ink hover:bg-ground"
            }`}
          >
            {t.label}
            {t.count !== null && <span className="rounded-full bg-ground px-2 text-[13px] font-bold tabular-nums">{t.count}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`hh-panel-${tab}`} aria-labelledby={`hh-tab-${tab}`} className="pt-3">
        {tab === "categories" && <Categories account={account} cats={cats} busy={busy} act={act} />}
        {tab === "rules" && <Rules account={account} cats={cats} rules={rules} busy={busy} act={act} />}
        {tab === "lines" && <Lines account={account} cats={cats} busy={busy} act={act} />}
      </div>
    </section>
  );
}

function Categories({ account, cats, busy, act }: { account: AccountInfo; cats: RtPersonalCategory[]; busy: string | null; act: Act }) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [added, setAdded] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const nameOf = (c: RtPersonalCategory) => names[c.id] ?? c.name;
  const changed = cats.some((c) => names[c.id] !== undefined && names[c.id].trim() !== c.name);
  const list = (drop?: string, extra?: string) => [
    ...cats.filter((c) => c.id !== drop).map((c) => ({ id: c.id, name: nameOf(c).trim() || c.name })),
    ...(extra ? [{ id: null, name: extra }] : []),
  ];

  async function save(body: { id: string | null; name: string }[], done: string) {
    if (await act("categories", () => runtime.personal.saveCategories(account, body), done)) {
      setNames({});
      setRemoving(null);
      return true;
    }
    return false;
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col divide-y divide-border">
        {cats.map((c) => (
          <li key={c.id} className="flex flex-col gap-2 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-muted">
                <span className="sr-only">Name of the category {c.name}</span>
                <input
                  value={nameOf(c)}
                  onChange={(e) => setNames({ ...names, [c.id]: e.target.value })}
                  disabled={c.id === OTHER}
                  className={`${input} w-full max-w-sm disabled:bg-ground`}
                />
              </label>
              {c.id === OTHER ? (
                <span className="text-sm text-muted">Always here: anything no rule recognises</span>
              ) : (
                <button type="button" disabled={busy !== null} onClick={() => setRemoving(c.id)} className={link} aria-label={`Remove category ${c.name}`}>
                  Remove
                </button>
              )}
            </div>
            {removing === c.id && (
              <div role="group" aria-label={`Remove ${c.name}?`} className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-bg px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 text-warn-ink">
                  Remove {c.name}? Its budget goes with it. A category a rule or a hand-set line still uses can&apos;t be removed.
                </span>
                <button type="button" disabled={busy !== null} onClick={() => save(list(c.id), `Removed ${c.name}`)} className={quiet}>
                  Remove {c.name}
                </button>
                <button type="button" onClick={() => setRemoving(null)} className={link}>
                  Keep it
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy !== null || !changed} onClick={() => save(list(), "Category names saved")} className={button}>
          Save names
        </button>
      </div>
      <div className="flex flex-col gap-2 min-[560px]:flex-row min-[560px]:items-end">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-bold text-ink">
          New category
          <input value={added} onChange={(e) => setAdded(e.target.value)} placeholder="Pets" maxLength={40} className={input} />
        </label>
        <button
          type="button"
          disabled={busy !== null || !added.trim()}
          onClick={async () => {
            if (await save(list(undefined, added.trim()), `Added ${added.trim()}`)) setAdded("");
          }}
          className={button}
        >
          Add category
        </button>
      </div>
    </div>
  );
}

function Rules({
  account,
  cats,
  rules,
  busy,
  act,
}: {
  account: AccountInfo;
  cats: RtPersonalCategory[];
  rules: RtPersonalRule[];
  busy: string | null;
  act: Act;
}) {
  const [rule, setRule] = useState({ value: "", category: cats.find((c) => c.id === "groceries")?.id ?? cats[0]?.id ?? OTHER });
  const catName = (id: string) => cats.find((c) => c.id === id)?.name ?? id;

  async function addRule() {
    const value = rule.value.trim();
    if (!value) return;
    // Cleared now, not after the page reloads its figures, so a rule typed meanwhile is not wiped; put back if refused.
    setRule((r) => ({ ...r, value: "" }));
    if (!(await act("rule", () => runtime.personal.addRule(account, value, rule.category), `Payments containing "${value}" now go to ${catName(rule.category)}`)))
      setRule((r) => (r.value ? r : { ...r, value }));
  }

  function move(i: number, by: -1 | 1) {
    const ids = rules.map((r) => r.id);
    [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
    const r = rules[i];
    void act(`move-${r.id}`, () => runtime.personal.reorderRules(account, ids), `Moved the rule for ${r.match.value} ${by < 0 ? "up" : "down"}`);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 min-[560px]:flex-row min-[560px]:items-end">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-bold text-ink">
          When the payment contains
          <input value={rule.value} onChange={(e) => setRule({ ...rule, value: e.target.value })} placeholder="TESCO" className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-bold text-ink">
          Put it in
          <select value={rule.category} onChange={(e) => setRule({ ...rule, category: e.target.value })} className={input}>
            {cats.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={addRule} disabled={busy !== null || !rule.value.trim()} className={button}>
          Add rule
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy !== null}
          className={quiet}
          onClick={() =>
            act("starter", () => runtime.personal.addStarterRules(account), (got) =>
              got.length ? `Added ${got.length} common UK merchants` : "Those common UK merchants are already there",
            )
          }
        >
          Add common UK merchants
        </button>
      </div>
      {rules.length === 0 ? (
        <p className="text-sm text-muted">No rules yet. Until there are, every payment sits under Other.</p>
      ) : (
        <ol aria-label="Rules, first match wins" className="flex flex-col divide-y divide-border text-sm">
          {rules.map((r, i) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="w-6 shrink-0 text-right font-bold tabular-nums text-muted">{i + 1}.</span>
              <span className="min-w-0 flex-1 break-words">
                Contains <strong>{r.match.value}</strong> → {catName(r.category_id)}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  disabled={busy !== null || i === 0}
                  onClick={() => move(i, -1)}
                  aria-label={`Move rule ${r.match.value} up`}
                  className={`${link} disabled:opacity-40`}
                >
                  Up
                </button>
                <button
                  type="button"
                  disabled={busy !== null || i === rules.length - 1}
                  onClick={() => move(i, 1)}
                  aria-label={`Move rule ${r.match.value} down`}
                  className={`${link} disabled:opacity-40`}
                >
                  Down
                </button>
                <button
                  type="button"
                  aria-label={`Delete rule ${r.match.value}`}
                  disabled={busy !== null}
                  onClick={() => act(`del-${r.id}`, () => runtime.personal.deleteRule(account, r.id), "Rule deleted")}
                  className={link}
                >
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const SOURCE: Record<string, string> = { rule: "by a rule", hand: "set by you", none: "no category yet" };

function Lines({ account, cats, busy, act }: { account: AccountInfo; cats: RtPersonalCategory[]; busy: string | null; act: Act }) {
  const [lines, setLines] = useState<RtBankLine[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [shown, setShown] = useState(PAGE);

  const load = useCallback(async () => {
    try {
      const all = await runtime.bank.lines(account);
      // Money out the household rules sort; income, transfers and ignored lines are not categorised.
      const out = all.filter((l) => l.amount_pence < 0 && l.household_source !== "excluded" && l.household_source !== "income");
      setLines(out.sort((a, b) => b.date.localeCompare(a.date)));
      setFailed(null);
    } catch (e) {
      setFailed((e as Error).message);
    }
  }, [account]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function put(l: RtBankLine, categoryId: string | null) {
    const name = categoryId ? (cats.find((c) => c.id === categoryId)?.name ?? categoryId) : null;
    if (
      await act(
        `line-${l.id}`,
        () => runtime.personal.setLineCategory(account, l.id, categoryId),
        name ? `Put ${l.description || "the line"} in ${name}` : `${l.description || "The line"} goes back to the rules`,
      )
    )
      await load();
  }

  if (failed) return <p className="text-sm text-muted">The bank lines couldn&apos;t be read just now ({failed}).</p>;
  if (lines === null) return <p className="text-sm text-muted">Loading the lines…</p>;
  if (lines.length === 0)
    return (
      <p className="text-sm text-muted">
        No payments yet. Import a statement on the{" "}
        <a href="/bank" className="font-bold text-teal-dark underline">
          Bank
        </a>{" "}
        page.
      </p>
    );
  const open = lines.filter((l) => l.household_sorted === false);
  const rows = (onlyOpen ? open : lines).slice(0, shown);
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-2 text-[15px] text-ink">
        <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} className="h-5 w-5 accent-teal" />
        Only lines with no category ({open.length})
      </label>
      {rows.length === 0 ? (
        <p className="text-sm font-semibold text-teal-dark">All sorted: every payment has a category.</p>
      ) : (
        <ul aria-label="Bank lines" className="flex flex-col divide-y divide-border">
          {rows.map((l) => {
            const source = l.household_source ?? "none";
            return (
              <li key={l.id} className="flex flex-col gap-2 py-3 min-[640px]:flex-row min-[640px]:items-center">
                <div className="min-w-0 flex-1">
                  <p className="break-words text-[15px] font-semibold text-ink">{l.description || "—"}</p>
                  <p className="text-sm text-muted">
                    {ukDate(l.date)} · <span className="tabular-nums">{pounds(-l.amount_pence)}</span> · {SOURCE[source] ?? source}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 text-sm text-muted">
                    <span className="sr-only">Category for {l.description || "this line"} on {ukDate(l.date)}</span>
                    <select
                      value={source === "none" ? "" : (l.household_category_id ?? "")}
                      disabled={busy !== null}
                      onChange={(e) => e.target.value && void put(l, e.target.value)}
                      className={input}
                    >
                      {source === "none" && <option value="">Choose a category…</option>}
                      {cats.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {source === "hand" && (
                    <button type="button" disabled={busy !== null} onClick={() => void put(l, null)} className={link} aria-label={`Use the rules for ${l.description || "this line"}`}>
                      Use the rules
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {(onlyOpen ? open : lines).length > shown && (
        <button type="button" onClick={() => setShown(shown + PAGE)} className={`${quiet} self-start`}>
          Show {PAGE} more
        </button>
      )}
    </div>
  );
}
