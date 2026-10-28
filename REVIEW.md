# Phone overflow: review notes

## What changed
- `apps/web/e2e/phone.spec.ts`: new block "360 px wide (small Android), every nav page". For each of the 13 nav pages (Home, Review, Ask, Invoices, Bank, VAT, Jobs, Payroll, Reports, Contacts, Vehicles, Files, Settings) at 360x740 it waits for `networkidle`, then for no `[aria-busy]`, no `.animate-pulse` skeleton and no "Loading…" text in `main`, then two animation frames, and only then checks `scrollWidth <= clientWidth` on `document.documentElement`. On failure the message names the element whose right edge is furthest past the viewport.
- CSS only, VAT page, no change at desktop width: `overflow-wrap: anywhere` on the period heading (`LiveVat`), the confirm heading (`ConnectHmrc`) and the period picker labels and detail text (`VatPeriodPicker`); the HMRC confirm table is wrapped in `overflow-x-auto`.

## Honest finding
No overflow could be reproduced. The old test checked right after `networkidle`, which can fire before the VAT data has rendered; the new test removes that race. The CSS changes are precautionary guards against long period labels and keys, not fixes for an observed overflow. The original one-off failure remains unexplained.

## Results
- Lint: clean. `e2e:build` OK. `e2e:test` full run: 221 passed, 58 skipped, 0 failed.
- Phone project, `--repeat-each=5`, before the CSS change: 480 passed, 145 skipped, 0 failed (includes 65/65 of the new 360 px tests).
- After the CSS change, new 360 px tests only, `--repeat-each=5`: 64/65 passed. The one failure was in test setup (`createBooksFolder`, "Your folder is ready." not seen within 10 s), not an overflow. The machine was shared with another Playwright run (load average about 19), so this is timing noise.

## Check on a real phone (about 360 px wide)
1. /vat: pick each period in the picker, including the oldest; labels and "filed with HMRC as <key>" text should wrap, with no sideways scroll.
2. /vat with HMRC connected (sandbox): the "Confirm VAT return" step, with its long period key in the heading and the box table.
3. Rotate to landscape and back on /bank and /contacts; tables should scroll inside their own box, never the page.
