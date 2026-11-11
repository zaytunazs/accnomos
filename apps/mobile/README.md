# accnomos_mobile

Flutter app (Android, and iOS from Nov 2026) for Accnomos: bookkeeping and
VAT for UK small businesses, a thin client over the same runtime API as the
web app.

- iOS / App Store: [`docs/IOS_APP_STORE.md`](../../docs/IOS_APP_STORE.md) —
  owner steps, signing, CI (`.github/workflows/ios.yml`), review notes. iOS
  builds need a Mac (or the CI's hosted Mac); not yet compiled.

- Web parity: [`PARITY.md`](PARITY.md) — every web page/action against
  the phone (done / missing / web-only-by-design).
- Release notes: [`RELEASE_NOTES.md`](RELEASE_NOTES.md) (current 0.3.6+11).
- Gates: `flutter analyze`, `flutter test`, and
  `flutter build apk --debug --target-platform android-arm64`
  (Flutter at `C:\src\flutter\bin`).
