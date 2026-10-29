# Review and approve

Who this is for: an owner clearing the Review queue. AI proposes, code checks,
you approve: nothing posts on its own.

1. Open Review (`/review`) and read the queue counts.
   ![step 1](../howto/img/review-approve-1.png)
   Must be visible: the Review page with ready proposals counted separately
   from *Needs a look*.
   If this goes wrong: the queue is empty after a scan, so check the intake
   log for dropped files.
2. Open one card and compare every field against the receipt image.
   ![step 2](../howto/img/review-approve-2.png)
   Must be visible: the receipt image beside supplier, VAT number, date, net,
   VAT and total, with the reader line naming the Meta model.
   If this goes wrong: the image is unreadable, so reject the card and
   photograph the receipt again.
3. Read the code checks and the second reading before deciding.
   ![step 3](../howto/img/review-approve-3.png)
   Must be visible: the checks list (arithmetic, VAT number, duplicates) and
   the Verifier line, agreed or disagreeing.
   If this goes wrong: the two readings disagree, so the card sits in
   *Needs a look* with both values; pick the one the image supports.
4. Press Approve, Edit, or Reject.
   ![step 4](../howto/img/review-approve-4.png)
   Must be visible: the Approve, Edit and Reject buttons, and after approving,
   the posted confirmation.
   If this goes wrong: Approve stays disabled, so fill the highlighted missing
   field first.
5. Optional: tick *Always do this for this supplier* for Autopilot L1.
   ![step 5](../howto/img/review-approve-5.png)
   Must be visible: the Autopilot tick box on the Approve card and the rule
   saved notice.
   If this goes wrong: later receipts from that supplier still wait in Review,
   so check the rule totals: Autopilot only posts under twice the usual.
6. Undo a mistake from the ledger entry, never by deleting.
   ![step 6](../howto/img/review-approve-6.png)
   Must be visible: the entry's *Undo* button and the reversing entry it
   creates.
   If this goes wrong: the period is already submitted, so the correction is
   dated today in the open period instead.
