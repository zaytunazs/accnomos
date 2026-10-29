# Income Tax quarterly update (sole trader or landlord)

Who this is for: a sole trader or landlord sending Making Tax Digital Income
Tax updates. Deadlines for standard quarters: 7 August, 7 November, 7 February
and 7 May, with Self Assessment on 31 January. HMRC contact is sandbox only.

1. Open Settings (`/settings`) and switch on *I am self-employed*.
   ![step 1](../howto/img/income-tax-update-1.png)
   Must be visible: Settings with the *I am self-employed* switch and the
   accounting basis choice (cash or traditional).
   If this goes wrong: nothing changes on Home, so check the switch saved for
   this device.
2. Landlords: register each property on Property (`/property`) first.
   ![step 2](../howto/img/income-tax-update-2.png)
   Must be visible: the property list with each registered address and its
   income for the year.
   If this goes wrong: rental income is missing below, so the property was
   never registered.
3. Open Self-employment (`/self-employment`) and connect HMRC's Income Tax
   scopes.
   ![step 3](../howto/img/income-tax-update-3.png)
   Must be visible: the connect button naming the Income Tax scopes, and the
   sandbox marker beside it.
   If this goes wrong: the connection asks for production, so stop: this
   product works in the sandbox only.
4. Check the SA103-style figures and the ledger lines behind each box.
   ![step 4](../howto/img/income-tax-update-4.png)
   Must be visible: turnover and expense boxes with totals and disallowables,
   each opening its ledger lines.
   If this goes wrong: a box misses a payment, so check the accounting basis:
   cash counts payments, traditional counts invoices.
5. Tick to confirm and submit the cumulative period summary.
   ![step 5](../howto/img/income-tax-update-5.png)
   Must be visible: the confirmation tick, the submitted summary, and the
   receipt saved under `_System/itsa/`.
   If this goes wrong: the page still shows the period open, so the submit
   never left; check the connection and retry.
6. Read HMRC's tax and NI calculation as HMRC's, not yours.
   ![step 6](../howto/img/income-tax-update-6.png)
   Must be visible: the calculation page labelled as HMRC's figures with any
   missing figure shown as a dash.
   If this goes wrong: a figure you expected is a dash, so HMRC left it out of
   the response; nothing is estimated.
