# Review: Personal finances on Android (`muse/android-personal`)

Reviewed by the integrator on 28 Oct 2026 before merging (the branch came without a review). Flutter only: a Personal
screen (month summary, budgets with progress, regular bills, savings goals), the *Show personal finances* switch in
Settings, client calls for `/personal/*`, and `test/personal_test.dart` (mock transport).

## Checked

- **Same feature as the web, same switch semantics.** Off by default (`accnomos.showPersonal`); More shows *Personal*
  only while it is on, like the web sidebar and menu bar (Settings › Show personal finances).
- **Same API.** `GET /personal/summary|budgets|recurring|goals` and `PUT /personal/budgets` with
  `{budgets: {category: pence}}` match `services/runtime/app/routes_personal.py` and `personal.BudgetsIn`; the phone
  reads the whole map before saving one category, so it never drops the others. Setting a budget is the only write.
- **Version.** The branch claimed 0.3.6+11, which `main` already used for the linked-mailboxes list. A Play version code
  can be used once, so this release is **0.3.7+12** (`pubspec.yaml`, `RELEASE_NOTES.md` has both entries).
- **Merge.** More keeps month-end's entry; Personal sits after it, before Reports.
- **Flutter gates** could not run in the integration container (no Flutter SDK); they ran in GitHub Actions' `flutter
  (analyze, test)` job on the integration commit before `main` moved (see `docs/reviews/integration/REVIEW.md`).

## What remains (from the branch's own notes)

- Not run on a phone against a real runtime with imported statements; the budget save round-trip and 360 dp layout on a
  real device need a human check.
