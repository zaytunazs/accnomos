# Release notes — Accnomos mobile

## 0.3.0 (version code 3)

Play "What's new" (433 characters):

Check receipts anywhere: approve, edit or reject each proposal, with undo
if you change your mind. Ask about your books and see the figures behind
every answer. Browse VAT, invoices, jobs, vehicles, bank and payroll from
the More tab. Figures are worked out by code from the books in your own
OneDrive. Sign in with Microsoft works only after the Entra hash is
registered; until then the app shows clearly labelled fictional samples.

## Emulator release check (0.3.0+3, debug APK, AVD accnomos_pixel)

- Signed-out walk of Home, Review (approve, edit sheet, undo), Ask
  (sample thread and action chips), VAT, More → Files, Contacts,
  Invoices, Jobs, Vehicles, Bank, Payroll, Settings: no exceptions and
  no RenderFlex overflows in `adb logcat`. No app fixes needed.
- Landscape on Home, Review and Ask: no overflow, state kept
  (Review stayed on its card, Ask kept its thread).
- Settings → Test connection against `http://10.0.2.2:8780`: connected;
  the reader answered with its local model list.
- Screenshots in `screenshots/` (1080×2400 PNG, each under 1 MB).
- `flutter analyze` clean, `flutter test` green.
