# Task: Integration review of main — make the whole thing coherent after a day of parallel merges

Accnomos monorepo (public; UK English; no secrets). You are reviewing `main` itself (not a feature branch). Read `README.md`, every
`docs/*.md`, every `docs/reviews/*/REVIEW.md` ("what remains" sections), then the code.

1. Run everything: `pytest -q` in `packages/*`, `services/runtime`, `services/hmrc-relay`; `cd apps/web && pnpm run build`; `cd apps/mobile &&
   flutter analyze` (if flutter is available here; otherwise note it). Fix failures at the root.
2. Cross-feature consistency: one `Books` folder layout (list every path the code writes under the user's folder and make sure
   `docs/ARCHITECTURE.md` matches); one way to read settings headers; one audit log format; navigation shows every page that exists and
   no page that doesn't; Books.xlsx sheets from all features rebuild without clashing; `runtime.ts` and `runtime_client.dart` cover every route.
3. Work through the "what remains" items from the review files: fix the ones that are small and clearly right; list the rest in
   `docs/REMAINING.md` grouped by feature with an honest severity.
4. Dead code, duplicate helpers, inconsistent naming (UK English, "VAT return", "Needs a look", "Approved by Autopilot") — tidy.
5. README "What works today" table: regenerate from reality, one row per feature, with the honest status words: *works end-to-end*,
   *works with fakes / needs a live run*, *UI only*, *not started*.
Commit in small steps; do not push. Finish with `git log --oneline -12` and the contents of `docs/REMAINING.md`.
