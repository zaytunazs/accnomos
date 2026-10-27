# Android parity: every web page has a phone path

Source of truth for what the web can do: `apps/web/src/app/**/page.tsx`
plus the components those pages render. Status as of the code on this
branch (see `git log` at the bottom for the audit commits).

Statuses: **done** (on the phone now) · **partial** (useful bits on the
phone, the rest behind a "Do this on the web" row) · **web-only**
(needs a desktop browser, with the reason).

"Do this on the web" rows in the phone UI open
`https://accnomos.com/<path>` (the production site) via the shared
`WebOnlyCard` widget (`lib/widgets/web_only.dart`).

## Pages and actions

| Web page / action | Phone status | Phone path or reason |
|---|---|---|
| `/` Home: greeting, figures, deadlines, activity | done | `HomeScreen` + `home_cards` (to-dos, inbox, plan-a-day) |
| `/` Setup checklist | done | Home setup checklist |
| `/` Ask bar | done | Home ask bar → `AskScreen` |
| `/` Inbox triage (summaries, draft replies) | done | Home inbox card (`mailTriage`, `draftReply`) |
| `/` Plan a day / apply to calendar | done | Home plan card (`planDay`, `applyPlan`) |
| `/` To-dos add / tick off | done | Home to-dos (`todos`, `addTodo`, `deleteTodo`) |
| `/review` approve / edit / reject proposals | done | `ReviewScreen` + edit sheet |
| `/review` bulk approve rule matches + undo | done | `ReviewScreen` (approve-all, undo) |
| `/ask` ask + voice ask + action cards | done | `AskScreen` (voice via `askVoice`) |
| `/vat` 9 boxes + period picker | done | `VatScreen` (calendar quarters; stagger saves but only the web sends it — see HONESTY) |
| `/vat` Connect HMRC, obligations, submit return | web-only | Oasis filing needs the browser OAuth redirect + declaration flow; phone shows "Do this on the web" → `/vat` |
| `/invoices` list + filter by status | done | `InvoicesScreen` |
| `/invoices/new` draft → preview → confirm send | done | `NewInvoiceScreen` (draft, runtime totals) → preview (`invoicePdf`) → `confirmAndSend` dialog |
| `/invoices` record / remove payment, credit notes, void, reminders, mark paid | done | `InvoicesScreen` + `payments_sheets` (payments, credit notes, void) |
| `/invoices` invoice profile + logo upload | partial | Business group edits address/terms/bank; logo upload stays on the web → `/settings#invoice-profile` |
| `/bank` statements + unmatched lines | done | `BankScreen` |
| `/bank` confirm a single sure match | done | `BankScreen` (only when the runtime returns exactly one suggestion) |
| `/bank` CSV upload | web-only | Picking + uploading a CSV is a desktop task; "Do this on the web" → `/bank` |
| `/bank` unmatch / transfer / ignore / expense proposal / post-as-payment / confirm-all-exact / reconcile | web-only | Ambiguous money movement stays deliberate on a big screen; links → `/bank` |
| `/bank` rules add / edit / delete | done | `BankScreen` rules section + rule sheet (`createBankRule`, `updateBankRule`, `deleteBankRule`) |
| `/bank` rules reorder | web-only | Ordering 200 ids is fiddly on a phone; "Do this on the web" → `/bank` |
| `/contacts` list, balances, statements, edit, payment terms | done | `ContactsScreen` |
| `/contacts` import from Outlook / add from phone | done | Settings/Contacts import + `phone_import_sheet` |
| `/contacts` merge duplicates + undo merge | web-only | Side-by-side AI judgement needs a wide screen; link → `/contacts` |
| `/contacts` HMRC VAT-number check | web-only | Sandbox check with explanatory copy lives on the web; link → `/contacts` |
| `/contacts` apply credit / refund credit | done | Contacts detail (`applyCredit`, `refundCredit`) |
| `/jobs` list + quick timesheet add | done | `JobsScreen` + `AddTimesheetScreen` |
| `/jobs` job detail, job CRUD, timesheet edit/delete, invoice-from-job | web-only | Desk work with rates and hours tables; links → `/jobs` |
| `/vehicles` mileage list + log a journey | done | `VehiclesScreen` + `AddMileageScreen` |
| `/vehicles` vehicle add/edit/delete, journey edit/delete, quarterly allowance claim | web-only | Claim flow waits in Review on the web; links → `/vehicles` |
| `/payroll` pay-run estimates | done | `PayrollScreen` (read-only) |
| `/payroll` prepare / edit / export / confirm / reopen | web-only | Estimates are confirmed with the provider's actuals on the web; links → `/payroll` |
| `/reports` P&L, aged, VAT, trend + save to 07 Reports | done | `ReportsScreen` (`reportExport`) |
| `/files` OneDrive folder view | done | `FilesScreen` (OneDrive links open externally) |
| `/files` rebuild Books.xlsx now | web-only | One tap on the web (`/files`); the file still rebuilds itself after every action |
| `/settings` Connection (sign-in, reader, disconnect) | done | Settings › Connection (MSAL sign-in, reader address, disconnect) |
| `/settings` AI choice + test | done | Settings › AI (local/key, test connection) |
| `/settings` Automation (level, rules, inbox, intake, triage, working hours) | partial | Level (L1/L2), Autopilot rules remove, inbox check; triage defaults, intake toggle and working hours stay on the web → `/settings#automation` |
| `/settings` Business (details, VAT periods, invoice profile, staff) | partial | Name, VAT number, stagger, invoice basics; staff list stays on the web → `/settings#settings-staff` |
| `/settings` Your data: export, where-stored, leave | done | Settings › Your data (`booksExport` → zip in 07 Reports/Exports; disconnect clears the phone) |
| `/audit` trail list | done | `AuditScreen` (last 31 days, newest first) |
| `/audit` who/kind/date filters | done | `AuditScreen` filter chips (actor + kind + from/to, same query as the web) |
| `/audit` CSV export | web-only | File download needs a browser; "Do this on the web" → `/audit` |
| `/connect`, `/connect/ai`, `/connect/business`, `/connect/ready` onboarding | web-only-by-design | The phone signs in with MSAL in Settings › Connection; there is no browser onboarding funnel on Android |
| `/how-it-works` explainer | web-only-by-design | Marketing/explainer copy; nothing to do in the app |
| `/privacy` privacy policy | web-only-by-design | Policy document; linked from Settings › Your data ("what is stored where") |
| Planner travel/visit-length settings | web-only | Tuned alongside the plan on Home web; the phone plans with defaults |

## What this audit delivers (0.3.4+9)

- Bank rules are no longer read-only: add, edit (sheet) and delete
  (confirmed) from `BankScreen`; reorder stays on the web.
- Settings › Your data: export trigger (`POST /books/export`), a plain
  list of what lives where, and the leave path. Invoice draft → preview →
  confirm send was already on the phone and is covered by widget tests.
- `AuditScreen` has who/kind/date filters using the same `GET /audit`
  query parameters as the web.
- Every remaining web-only action has a "Do this on the web" row with
  the exact page link.
