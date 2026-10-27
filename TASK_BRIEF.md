# Task: One source of truth for the books folder layout (runtime, web, Android, docs, README.txt in the user's OneDrive)

Accnomos monorepo (public; UK English; no secrets). The onboarding tree and the Files page show `02 Sales invoices` / `04 Needs a look`
while invoicing writes `03 Sales/invoices/`, bank writes `03 Bank statements/`, payroll `04 Payroll/`, VAT `05 VAT returns/`
(see `docs/reviews/e2e-all-pages/REVIEW.md` "Folder names disagree"). Read first: every path constant in `services/runtime/app/*.py`
(`grep -n '"0[0-9] ' services/runtime/app`), `packages/connectors/src/accnomos_connectors/*.py` (folder creation, README.txt text),
`apps/web/src/lib/{graph.ts,folders*.ts}`, `components/files/*`, `components/connect/*`, `apps/mobile/lib/services/graph.dart`,
`docs/ARCHITECTURE.md` layout table, `tools/seed_demo.py`.

## Decision (taken; do not reopen)
Canonical top-level folders: `00 Inbox`, `01 Receipts`, `02 Needs a look`, `03 Sales` (with `invoices/`, `invoices/sent/`),
`03 Bank statements` → rename to `04 Bank statements`, `04 Payroll` → `05 Payroll`, `05 VAT returns` → `06 VAT returns`,
`06 Reports` → `07 Reports`, `_System/*` unchanged. Existing users' folders: on first contact after this change the runtime
**moves** an old-named folder to the new name once (Graph PATCH parentReference/name; fake storage equivalent), audited, never
copies or deletes; if both old and new exist it leaves them and warns in `/health` + Files page.

## Deliverables
1. `services/runtime/app/paths.py` (or extend the existing module) is the only place the names live; every module imports from it.
   The connector's README.txt text is generated from it. Tests: no string literal `"0[0-9] "` outside `paths.py` (a test greps the tree).
2. Web `lib/folders.ts` and Android `graph.dart` carry the same list (generated check: a test compares the three lists byte for byte
   via a small JSON fixture `packages/.../folders.json` consumed by all three).
3. The one-time migration above with tests on fake storage (old → new, both-present warning, idempotent).
4. `docs/ARCHITECTURE.md`, `docs/DEMO.md`, README rows, `tools/seed_demo.py`, e2e specs updated; `pytest`, `pnpm run build`, e2e
   suite (`pnpm run e2e` in test mode) all green; `flutter analyze` cannot run here — keep the Dart change to the list only.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify on a real OneDrive.
