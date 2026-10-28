# Cloud session brief (common rules)

Repo zaytunazs/accnomos (public; Accnomos: AI bookkeeping + MTD for UK small businesses, sole traders, landlords and personal finances; FastAPI runtime services/runtime/app, packages/ledger, HMRC relay services/hmrc-relay, Next.js static web apps/web with Playwright e2e in test mode, Flutter apps/mobile; product rules: no user database (each user's books live in their own OneDrive), AI proposes / user approves / code calculates in pence, HMRC: production use produces files ready for submission while direct submission stays in HMRC's sandbox for judges).
Read README.md, docs/ARCHITECTURE.md, docs/HONESTY.md, docs/research/FEATURES_COMPARISON.md on origin/claude/research-features, and run `git branch -r` (many features live on claude/* branches being merged into main by an integrator).
UK English.
Never commit secrets or a .v/.venv folder; never push to main; no PR.
Do not call Meta's API, Baseten or Modal.
Verify every tax/legal rule on gov.uk or the official source and cite URL + date checked in code comments and docs.
Gates before pushing: set up per docs/DEV.md incl.
dev deps; cd services/runtime && python -m pytest -q all pass; ruff check .
&& ruff format --check .
clean; pyright services/runtime/app 0 errors; cd apps/web && pnpm install --frozen-lockfile && pnpm exec eslint .
&& pnpm run e2e:build && pnpm run e2e:test all pass; Flutter changes need widget tests (flutter analyze/test if available).
Update docs/HONESTY.md (what is untested against real services) and write docs/reviews/<branch>/REVIEW.md (sources, design, tests with counts, risks).
Commit per step, push your branch, end with a short summary.


# Tasks

## accountant (branch claude/accountant)

TASK: accountant collaboration and an accountant portal. (1) Invite your accountant: the client invites an accountant by email; with no database, access is granted by sharing the client's Accnomos books folder through Microsoft Graph (driveItem invite with read or edit role; check whether the personal-account app folder can be shared, and if not offer the work-account /Accnomos folder or a dedicated shared folder: verify on learn.microsoft.com and cite) and recording the invitation in the client's _System/accountant.json; revoke = remove the permission. (2) Opt in to reviews by 'Accnomos accountants' (the operator's own accounting team): a separate explicit opt-in with clear consent text (what they can see, read or edit, how to stop), stored in the client's books, which shares the folder with the operator team's Microsoft account set in server env ACCOUNTANT_TEAM_EMAIL (empty = option hidden). (3) Accountant portal: an accountant signs in with Microsoft; the portal lists every Accnomos books folder shared with them (Graph sharedWithMe, filtered to folders that contain _System/profile.json or the Accnomos tree), shows per client: name, kind, VAT/MTD deadlines, items waiting in Review, open queries, last activity; opens a client in a read-only or edit view using the same app pages against the shared drive item (the runtime must accept a target drive id + item id for a shared folder; keep path-safety and never mix clients' caches). (4) Client queries: the accountant can leave a query on a transaction or document; it appears as a to-do for the client and both see the thread; stored in the client's books (_System/queries/). (5) Accountant actions are audited with the accountant's identity. Web pages /accountant (portal) and Settings > Your accountant; Android: show the accountant and queries read-only. Tests for sharing calls with fakes (documented Graph request/response shapes), consent and revoke, portal listing, cache isolation between clients, queries.

## cis (branch claude/cis)

TASK: Construction Industry Scheme and the VAT domestic reverse charge for trades. Subcontractor side first: register CIS status (gross / net 20% / 30%), invoices and quotes that show the CIS deduction on labour only (materials excluded), payments received net of deduction settle the invoice in full with the deduction posted as CIS suffered (tax paid on account), monthly payment and deduction statements from contractors read from the inbox (AI proposes, user approves), and year totals for the self-assessment / company return. Then the VAT domestic reverse charge for building and construction services (when it applies, end-user/intermediary statements, invoice wording, VAT return box treatment). Contractor side (CIS300 monthly return): produce the return data and an HMRC-ready file or summary; direct online submission is out of scope (state it). Also write evals/gold/gen_gold_cis.py: a Qwen-driven generator (OpenAI-compatible endpoint, default http://127.0.0.1:8000/v1/chat/completions, model qwen3.8-27b) for synthetic CIS statements and reverse-charge invoices where code fixes every figure, labelled exactly 'SAMPLE — FICTIONAL COMPANY' with the real em dash, runnable later on the owner's Spark, tested here with a stub.

## vat-schemes (branch claude/vat-schemes)

TASK: VAT schemes: Flat Rate Scheme (sector percentages, 1% first-year discount, limited cost trader 16.5% test, how boxes 1-9 are filled), Cash Accounting (VAT due on payments received/made; reuse any cash-basis logic on origin/claude/cash-basis if present, else implement cleanly), and Annual Accounting (interim payments, annual return). Per-business setting with eligibility checks and the dates it applies from; the VAT return, VAT reports and Ask facts use the selected scheme; switching scheme mid-period handled per HMRC rules. Tests with HMRC's worked examples where published.

## landlords (branch claude/landlords)

TASK: landlords and property income: property profile kind or sub-ledger, per-property tags on income and expenses, ownership shares for jointly owned property (split figures per owner), UK property income categories as in HMRC's MTD Property Business API and SA105, furnished holiday lets abolition from April 2025 (verify), mortgage interest restriction (basic-rate tax credit, not an expense), replacement of domestic items relief, and the MTD Income Tax property updates through the existing relay pattern in the sandbox (check origin/claude/self-employment for the relay design and reuse it). A light 'landlord mode' with a simple screen for one or two properties. Also write evals/gold/gen_gold_landlord.py, a Qwen generator for synthetic letting statements and property bills (same rules as other gold generators: code fixes every figure, exact label 'SAMPLE — FICTIONAL COMPANY', stub-tested).

## import-history (branch claude/import-history)

TASK: import history and opening balances when switching from Xero, QuickBooks Online, Sage (50 and Accounting), FreeAgent or a spreadsheet: read their standard exports (trial balance, chart of accounts, contacts, open invoices and bills, bank balances; verify current export formats on the vendors' help pages and cite them), map accounts (editable mapping, unmapped flagged), post opening balances as one balanced opening journal at a chosen conversion date after the user approves, create contacts and open items so aged debtors/creditors are right from day one, and a reconciliation report that proves the imported TB equals the source TB. A wizard page /import. Tests with sample export files you write (fictional, labelled).

## bank-feeds (branch claude/bank-feeds)

TASK: bank feeds through an Open Banking aggregator. Research and compare UK providers that suit a stateless app (GoCardless Bank Account Data, TrueLayer Data API, Yapily, Plaid UK): pricing for small volumes, consent length (90-day reconsent and the 2025 FCA changes, verify), sandbox availability, token handling. Pick one, build it behind env vars (empty = feature off with a plain sentence), sandbox only by default. Because there is no database, store only what is unavoidable: the consent/requisition id and expiry in the user's books (_System/bankfeeds.json); tokens either short-lived and re-fetched per session, or encrypted with a server key if the provider requires a refresh token (explain the trade-off). Fetch transactions on app open into the existing bank-lines pipeline (dedupe against CSV imports by date/amount/reference), show reconsent dates and a 'reconnect' prompt before expiry, CSV import stays as the fallback. Tests with fakes built from the provider's documented shapes; e2e for connect, sync and dedupe in test mode.

