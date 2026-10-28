# Review: Android "Load sample books"

Branch `claude/android-sample`. Mirrors the web card (`apps/web/src/components/home/SampleBooks.tsx`) on the Flutter app.

## What changed (apps/mobile)
- `lib/models/sample_books.dart`: `SampleStatus` (state, step, done, total, steps, error, business, empty) and `SampleNote`.
- `lib/services/runtime_client.dart`: `sampleBooksStatus()` (GET /books/sample), `loadSampleBooks({carryOn})` (POST /books/sample or /continue). Same headers as every books call. A 409/429/503 carrying a `detail` sentence throws `SampleNote` (a note); anything else non-2xx goes through `_fail` as before.
- `lib/screens/sample_books_card.dart`: `SampleBooksCard`, `SampleProgress`, `SampleBanner`. Shown when state is `none` with `empty: true`, or `running`/`needs_token`/`failed`. Polls every 3 s while running; POSTs `/continue` every 4 min (counted in polls, not wall-clock) and on `needs_token`. Polling pauses when the Home tab is hidden (`TickerMode`) or the app is backgrounded. On a running-to-done transition it calls `onLoaded` once (Home reloads) and the card becomes the "SAMPLE — FICTIONAL COMPANY" banner (also shown on later visits when the status is `done`). Progress has a Semantics label ("Loading sample books, step N of M: name").
- `lib/screens/home_screen.dart`: the card sits under the tiles, signed-in only.
- `test/sample_books_test.dart`: client wire shape, 409 note, card states, polling, continue, done, 360 dp.
- `RELEASE_NOTES.md` 0.3.5 (code 10), `pubspec.yaml` 0.3.5+10, `PARITY.md` row.

## Decisions
- `failed` also shows the card with "Carry on loading sample books" (as the web does), beyond the brief's list.
- No "All steps" list (web has one); the current step and count only.

## Untested
- Nothing was run: no Flutter SDK here. `flutter analyze` and `flutter test` still to do; expect possible lint nits (e.g. catch ordering, unused locals).
- Not run on a phone or against a real runtime/Graph. The 4-minute token hand-over is only unit-tested with fake time.
- Home gap: a hidden card still leaves a 12 dp spacer.
