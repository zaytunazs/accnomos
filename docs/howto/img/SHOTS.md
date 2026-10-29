# How-to screenshots

Made by `node tools/video/howto.ts` from the demo sandbox (the fictional sample books, test-mode build). Each picture is
1440 × 900, cropped round the control the step names, with an amber box on it. Steps that happen outside the app
(a Microsoft consent screen, HMRC's sign-in, Basic PAYE Tools) show the app's side of the step; rows marked
*approximate* found no named control and show the whole page. Re-shoot those by hand if the step needs more.

| Image | Page | Control boxed | Must be visible |
|---|---|---|---|
| `add-mailbox-1.png` | `/settings` | none found: whole view (approximate) | the Settings page with the Outlook intake section and its off switch. |
| `add-mailbox-2.png` | `/settings` | Connections | the consent screen asking for Mail.Read and nothing wider. |
| `add-mailbox-3.png` | `/settings` | Connections | the mailbox address, the watched folder (Inbox), and the sender list. |
| `add-mailbox-4.png` | `/files` | _System | the run log in _System/Intake/ with kept and dropped counts. |
| `add-mailbox-5.png` | `/review` | Approve (post to books) | one card per receipt with supplier, date and totals filled in, and the intake source line. |
| `connect-books-1.png` | `/connect` | none found: whole view (approximate) | the Connect page with both options, Connect with Microsoft and Try the demo — no sign-in. |
| `connect-books-2.png` | `/` | SAMPLE — FICTIONAL COMPANY | the demo sandbox banner reading SAMPLE — FICTIONAL COMPANY over the Home dashboard. |
| `connect-books-3.png` | `/` | Cash in bank | the Home dashboard filling in with the sample company's cash, owed and deadlines cards. |
| `connect-books-4.png` | `/files` | 00 Inbox | the Apps/Accnomos tree with 00 Inbox to 06 folders and _System, plus file counts. |
| `connect-books-5.png` | `/files` | Books.xlsx | Books.xlsx with its README sheet saying it is generated. |
| `export-accountant-1.png` | `/reports/exports` | Find a report | the report list with the period controls and the period shown in the address. |
| `export-accountant-2.png` | `/reports/exports` | VAT return | the VAT-return export matching the boxes on /vat for the same period and scheme. |
| `export-accountant-3.png` | `/reports/exports` | none found: whole view (approximate) | the SA103 summary with turnover, expenses and the ledger lines behind each box. |
| `export-accountant-4.png` | `/reports/exports` | Audit | the ledger and audit exports with every column heading kept, even for an empty section. |
| `export-accountant-5.png` | `/files` | 07 Reports | the dated files in 07 Reports/ and the current Books.xlsx on Files. |
| `income-tax-update-1.png` | `/settings` | I am self-employed | Settings with the I am self-employed switch and the accounting basis choice (cash or traditional). |
| `income-tax-update-2.png` | `/property` | none found: whole view (approximate) | the property list with each registered address and its income for the year. |
| `income-tax-update-3.png` | `/self-employment` | Sandbox · test data only | the connect button naming the Income Tax scopes, and the sandbox marker beside it. |
| `income-tax-update-4.png` | `/self-employment` | none found: whole view (approximate) | turnover and expense boxes with totals and disallowables, each opening its ledger lines. |
| `income-tax-update-5.png` | `/self-employment` | none found: whole view (approximate) | the confirmation tick, the submitted summary, and the receipt saved under _System/itsa/. |
| `income-tax-update-6.png` | `/self-employment` | none found: whole view (approximate) | the calculation page labelled as HMRC's figures with any missing figure shown as a dash. |
| `invite-accountant-1.png` | `/settings` | Your accountant | the Invite your accountant section with the email box and access choice. |
| `invite-accountant-2.png` | `/settings` | Your accountant | the address typed in full and the selected access level. |
| `invite-accountant-3.png` | `/settings` | Your accountant | the sent confirmation naming the address invited. |
| `invite-accountant-4.png` | `/accountant` | none found: whole view (approximate) | your books listed under their Accountant page with the access level shown. |
| `invite-accountant-5.png` | `/audit` | none found: whole view (approximate) | the audit trail (/audit) with their actions under their name. |
| `payroll-paye-1.png` | `/payroll` | none found: whole view (approximate) | the employee list with name, tax code and starter declaration for each. |
| `payroll-paye-2.png` | `/payroll` | none found: whole view (approximate) | the pay-run form with hours, rate and gross per employee. |
| `payroll-paye-3.png` | `/payroll` | none found: whole view (approximate) | gross, tax, National Insurance and net per employee, with the estimate marker. |
| `payroll-paye-4.png` | `/payroll` | none found: whole view (approximate) | the download buttons for payslips, RTI files and the pension schedule, all for the same period. |
| `payroll-paye-5.png` | `/payroll` | none found: whole view (approximate) | Basic PAYE Tools with the filed submission beside the Accnomos files they came from. |
| `payroll-paye-6.png` | `/bank` | none found: whole view (approximate) | the bank payment matched against the pay run in Bank. |
| `reconcile-bank-1.png` | `/bank` | none found: whole view (approximate) | the Bank page with the file picker and the supported layouts note (Barclays, Starling, Tide, Monzo, HSBC, Lloyds). |
| `reconcile-bank-2.png` | `/bank` | 04 Bank statements/ | the saved statement file named by date and bank, with the line count. |
| `reconcile-bank-3.png` | `/bank` | none found: whole view (approximate) | each suggestion with amount within 1p, date within 5 days, and the counterparty name. |
| `reconcile-bank-4.png` | `/bank` | none found: whole view (approximate) | the Create expense proposal, Mark as transfer and Ignore buttons on an unmatched line. |
| `reconcile-bank-5.png` | `/bank` | Reconciled to date | the reconciled-to date on the tile and matching statuses in the Bank sheet of Books.xlsx. |
| `review-approve-1.png` | `/review` | none found: whole view (approximate) | the Review page with ready proposals counted separately from Needs a look. |
| `review-approve-2.png` | `/review` | Net · VAT · Total | the receipt image beside supplier, VAT number, date, net, VAT and total, with the reader line naming the Meta model. |
| `review-approve-3.png` | `/review` | Why: | the checks list (arithmetic, VAT number, duplicates) and the Verifier line, agreed or disagreeing. |
| `review-approve-4.png` | `/review` | Approve (post to books) | the Approve, Edit and Reject buttons, and after approving, the posted confirmation. |
| `review-approve-5.png` | `/review` | none found: whole view (approximate) | the Autopilot tick box on the Approve card and the rule saved notice. |
| `review-approve-6.png` | `/review` | Undo | the entry's Undo button and the reversing entry it creates. |
| `vat-return-1.png` | `/vat` | VAT period | the quarter picker with the current period and the nine boxes worked out by code. |
| `vat-return-2.png` | `/vat` | Entries | one open box with the entries that make up its figure. |
| `vat-return-3.png` | `/vat` | Connect to HMRC (simulated) | the sandbox connect button and the HMRC sign-in, with no production address anywhere. |
| `vat-return-4.png` | `/vat` | Connect to HMRC | HMRC's obligations list beside your periods, with any date mismatch explained in plain words. |
| `vat-return-5.png` | `/vat` | Connect to HMRC | the legal declaration wording with the tick box and the Submit to HMRC (sandbox) button. |
| `vat-return-6.png` | `/files` | 06 VAT returns | the receipt file in the period folder and the submitted marker on /vat. |
| `voice-chat-1.png` | `/ask` | none found: whole view (approximate) | the Ask thread with your question and the answer beside its cited book figures. |
| `voice-chat-2.png` | `/ask` | Ask your books | the recording state, then your words as the message: "Andy did 2 hours overtime at double time on the Hendon job". |
| `voice-chat-3.png` | `/ask` | none found: whole view (approximate) | the timesheet card naming Andy, 2 hours, double time and the Hendon job, with Approve, Change and Reject. |
| `voice-chat-4.png` | `/jobs` | none found: whole view (approximate) | the posted timesheet on the Hendon job page. |
| `voice-chat-5.png` | `/ask` | Ask your books | the quote card with code-priced lines, and the to-do "Remember to order 2-inch bolts for the Hendon job". |
