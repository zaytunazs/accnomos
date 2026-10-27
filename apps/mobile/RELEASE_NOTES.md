# Release notes — Accnomos mobile

## 0.3.4 (version code 7)

Play "What's new" (348 characters):

Bank rules can be added, edited and deleted on the phone. Settings has
Your data: export everything as one zip to your OneDrive. The audit
trail has who, what and date filters like the web. Anything still
web-only (statement upload, HMRC filing, merges) now shows a "Do this
on the web" row with the exact page. Parity table: apps/mobile/PARITY.md.

Not yet run on a phone: the new rule sheet, export button, audit
filters and every web link need a human check on a real device.

## 0.3.3 (version code 6)

Play "What's new" (440 characters):

Invoices take payments on the phone: record a payment (part, all or more),
remove one, raise a credit note for the whole invoice or chosen lines, and
void with the reason kept. Contacts show credit on account with Apply credit
and Refund, Bills to pay with Record payment, and Payment terms (days).
Every action confirms first with the runtime's figures, shows its refusal
sentence, and refreshes afterwards. Figures stay the runtime's job.

Not yet run on a phone: every payments sheet needs a human check on a real device.

## 0.3.2 (version code 5)

Play "What's new" (256 characters):

Contacts can now be added from the phone: pick people with Android's
own contact picker, mark each Customer, Supplier or Skip, and import
them to your books. Only the contacts you pick are read. No new app
permission, so no data-safety change for contacts.

## Emulator release check (0.3.2+5, pending a device run)

- `flutter analyze` clean, `flutter test` green (incl. the new
  `phone_import_test.dart`: mocked picker, kinds, duplicates, failure
  and 360 dp with no overflow).
- `uv run pytest services/runtime -q` green for the new
  `POST /contacts/import-phone` (`test_contacts.py`).
- No `READ_CONTACTS` in `AndroidManifest.xml`: the picker returns one
  contact URI with a one-time grant, read for name, emails, phones and
  postal address only; nothing is written back to the phone.
- Not yet run on a real phone: picker grant behaviour, repeated picks,
  the review sheet at small widths, the import summary and audit line,
  and sign-in-gated visibility still need a human check (see the five
  checks in the handover).

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
