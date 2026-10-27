# Release notes — Accnomos mobile

## 0.3.2 (version code 5)

Play "What's new" (440 characters):

Invoices take payments on the phone: record a payment (part, all or more),
remove one, raise a credit note for the whole invoice or chosen lines, and
void with the reason kept. Contacts show credit on account with Apply credit
and Refund, Bills to pay with Record payment, and Payment terms (days).
Every action confirms first with the runtime's figures, shows its refusal
sentence, and refreshes afterwards. Figures stay the runtime's job.

## 0.3.1 (version code 4)

Play "What's new" (361 characters):

Contacts show balances, statements and VAT status for each supplier
and customer. Settings is grouped into connection, AI, autopilot and
business. Capture queues several receipt photos, then reads them
together. Home lists your to-dos and inbox. Review approves all rule
matches at once, with undo. Signed out, everything is a clearly
labelled fictional sample.

## Emulator release check (0.3.1+4, debug APK, AVD accnomos_pixel)

- Signed-out walk of Home (to-dos, inbox), Review (bulk approve,
  edit sheet, image viewer, undo), Ask (sample thread), VAT,
  More → Files, Contacts (list, detail, VAT status), Invoices, Jobs,
  Vehicles, Bank, Payroll, Settings groups (Connection, AI,
  Automation, Business): no exceptions and no RenderFlex overflows
  in `adb logcat`.
- Capture multi-shot: two photos queued, "Read with Meta AI" offered.
- Landscape on Home, Review, Ask and Contacts: no overflow, state
  kept (Review stayed on its card, Ask kept its thread and draft).
- System dark mode: the app stays on its light theme
  (`ThemeMode.light`), so everything stays readable.
- AI Test connection needs sign-in: the button is disabled with an
  explanation while signed out. The connected and not-connected
  result lines are covered by widget tests.
- The live Ask action card and day-plan sheet need a signed-in
  account, so they were verified by widget tests, not on the device.
- Fixed: the contact VAT-number helper was cut to one line; it now
  shows in full. No crashes or overflows remained.
- Screenshots in `screenshots/` (1080×2400 PNG, each under 1 MB),
  adding `contacts.png` and `more.png`.
- `flutter analyze` clean, `flutter test` green.

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
