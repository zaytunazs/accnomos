# Accnomos: session handover (11 Nov 2026, ~16:00 UK), for the PayPal hackathon build

The Meta hackathon is finished (submitted 4 Nov). This handover is for the next session, which adapts Accnomos for the **PayPal hackathon**. **Stripe is on hold**: no live key exists, and the apps don't show it to users.

## Where the code is
- **`main` = `b5ab460`** (4 Nov). It is live: the web deploys itself from main, and the API runs on the Spark (`api.accnomos.com`). Nothing from this session is on main yet.
- **`integ/wave3` = `13ab33c`** (pushed). This is the branch to build on: everything below merged together, 30 commits ahead of main.
  - Runtime pytest: 3000 passed, 3 skipped. Web: lint, tsc and build pass, and prelaunch-words finds 0 hits.
  - Flutter (agent run): analyze is clean, 496 tests passed.
  - Playwright: all passing except `hmrc.spec.ts:8` and `sandbox.spec.ts:17`. Both fail on main's HMRC status merge too: there's an extra `/hmrc/status` call, which is not a billing problem.
- **`paypal-direct` = `0b46345`** (from the other session today, based on main). Payment links get a "direct" mode for the PayPal sandbox and Stripe test mode, and spoken invoices carry the link. It changes `routes_online_payments.py`, adds `tools/payments_sandbox_smoke.py` and adds the tests `test_online_payments_direct.py`. **It is not yet merged into integ/wave3. Merge it first**; it touches invoice payment links, not plan billing.
- Feature branches, all pushed and all inside integ/wave3:

  | Branch | What it is |
  |---|---|
  | `claude/google-drive` | Google Drive as storage, alongside OneDrive |
  | `claude/google-workspace` | Gmail, Calendar and Contacts |
  | `claude/android-google` | Google sign-in on Android |
  | `claude/ebay` | eBay seller OAuth, then auto-fetch of sales, refunds, fees, ads and payouts (Amazon later) |
  | `claude/private-prep` | CodeQL skips when the repo is private; `docs/PRIVATE_REPO_CHECKLIST.md` |
  | `integ/google-ebay` | The five branches above, merged |
  | `claude/bulk-drop` | Drop zips or whole folders into 00 Inbox (`apps/web/src/lib/bulk-intake.ts`) |
  | `claude/file-it-yourself` | VAT bridging CSV/XLSX, Income Tax quarterly figures and SA103S/F boxes; `HMRC_ENV` switch |
  | `claude/billing-api` | Supabase registry, plans, limits, promo codes, admin API, analytics, bug reports |
  | `claude/admin-ui` | Plans, billing and admin screens on web and Android |
  | `claude/ios-app` | iOS Xcode project, privacy manifest, TestFlight CI; `docs/IOS_APP_STORE.md` |
  | `claude/ai-local` | Our own server first, Anthropic as the backup; voice on our own server |

## Payments: how to add PayPal
- **Plan payments** use the backend setting `PAYMENTS_PROVIDER` (`none` by default, or `stripe`) in `services/runtime/app/billing/payments.py`, mirrored on the web in `apps/web/src/lib/payments.ts` / `NEXT_PUBLIC_PAYMENTS_PROVIDER`.
  - With `none`, checkout, the customer portal and top-up return 503 with a neutral sentence.
  - The web shows the plans, the trial and promo codes with: "Paid plans can't be bought here at the moment…". It shows no Stripe name.
  - `/account` returns `payments_provider`.
- **To add PayPal:**
  1. Add `paypal` to both `payments` modules.
  2. Write `paypal_api.py` next to `stripe_api.py`, covering PayPal Subscriptions (plans, subscribe, cancel) and its webhooks.
  3. Wire it through `routes.py` (`stripe_or_503`; make that a generic provider), `service.py` and `webhooks.py`.
  4. Use the fakes in `fakes.py` for tests.
  5. On the web, change `PlanBilling.tsx`, `PlanLimitDialog.tsx`, `PricingView.tsx`, `privacy/page.tsx` and `settings/billing` (`BillingReturn.tsx`).
  6. The contract test `tests/test_billing_contract.py` pins the shapes in `docs/billing/api_shapes.json`. Regenerate with `UPDATE_API_SHAPES=1`. Web check: `apps/web/tests/unit/api-shapes.test.ts`.
- **Invoice payment links** (customers paying a user's invoice) are a separate feature: `app/online_payments.py`, `routes_online_payments.py` and `components/settings/OnlinePayments.tsx`. `paypal-direct` extends this.
- **Plans:** Starter £10, Comprehensive £20, Ultimate £50 a month, ex VAT. Yearly is **2 months free** (£100 / £200 / £500).
  - 3-month free trial with no card. Admin-made promo codes, including 12 months free. The contract is in `docs/billing/PLANS_AND_CONTRACT.md`.
  - Live Supabase `accnomos.plans` holds 1000/2000/5000 (monthly) and 10000/20000/50000 (yearly), in pence.
- **iOS:** no prices, purchase links or "on the web" text (`StorePolicy.purchaseLinksAllowed`). Keep it that way for PayPal too.

## Stripe (on hold)
- Account: Zaytuna Business Services (`acct_1D1aqFJsZinhOryk`). The live restricted key was **not created**: Stripe asked for email verification at accounts@zaytunabusinessservices.co.uk, and that was stopped.
- Permissions chosen, for when it's resumed:
  - Customers, Checkout Sessions, Customer portal, Coupons, Prices, Products and Subscriptions: Write
  - Invoices: Read
  - Save the key with `set-env-secret.sh STRIPE_SECRET_KEY rk_live_`, then check it with `check-stripe.sh`.
- The Spark `.env` holds a **test** key (`sk_test`, verified). It does nothing while `PAYMENTS_PROVIDER=none`.
- Still to do when resumed: the webhook `https://api.accnomos.com/billing/stripe/webhook` and `STRIPE_WEBHOOK_SECRET`, the admin "Sync prices to Stripe" step, Stripe Tax (VAT GB441589282), the customer portal, and the trial-end reminder.
- Stripe owner task: upload a photo ID for Zohaib Sharif (overdue). Bacs, SEPA and Afterpay are paused.

## AI (claude/ai-local, merged into integ/wave3)
- The chain is our own server (vLLM on the Spark) first, then Anthropic (`claude-haiku-5-5`) as the backup. "Local only" never reaches Anthropic.
- Voice is spark-voice at `STT_BASE` (`http://host.docker.internal:8890`). SAM crop is off.
- Privacy text is updated (Anthropic, US, backup only; not used for training; 30-day deletion).
- `/health` only says "Accnomos AI". Full details are at `GET /admin/ai-status` (`ADMIN_EMAILS` only).
- **Not done:**
  - **Client side still shows model names:** "Read by Muse Spark" (`lib/meta-models.ts` `servedLine`, Android `proposal.dart`), the `/meta-models` page, `GET /ai/health` and `/ai/calls`, the Settings › AI routing names, and the marketing alt text.
  - **Bring your own AI is not started:** provider presets, model picker, Test button, keys sealed (AES-GCM) in `_System/`, an ask-before-fallback choice, the billing exemption, Android Settings, and their tests.
- **Not verified live:** Anthropic calls, reaching spark-voice from the container, and the image limits.

## Spark server (`ssh spark`, from the PC zs-pc01 via Desktop Commander)
- `.env` is `~/spark/accnomos/deploy-repo/.env`. Never print it.
- Set now: `AI_PROVIDERS=spark`, `SAM_CROP=0`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (`sb_secret`, verified), `ADMIN_EMAILS=admin@zaytunauk.co.uk`, and `STRIPE_SECRET_KEY` (test).
- Stale and unused: `MODEL_API_MODEL` and `VERIFIER_MODEL`, which still name Meta models.
- **At deploy:** set `ANTHROPIC_API_KEY` (from `~/.anthropic_key`) and `AI_PROVIDERS=spark,anthropic`. Keep `PAYMENTS_PROVIDER=none` until PayPal is ready. Redeploy with the new `deploy/docker-compose.yml`, which passes the new variables into the container.
- Helper scripts are in `~/spark/accnomos/ci/`:
  - `set-env-secret.sh NAME PREFIX`: the value goes in on stdin from the PC clipboard, then clear the clipboard.
  - `check-supabase.sh` and `check-stripe.sh`.
  - `acc-ci <branch>`: full CI on the Spark.
  - `ai-local-first.sh`.
- Deploy the API: `ssh spark "nohup bash ~/spark/accnomos/jobs/api_up.sh > ~/spark/accnomos/jobs/api_up.last.log 2>&1 &"`. It deploys from origin main. Then check `/health`.
- The Spark job queue `sq` can run batch, render and CI jobs, which saves Claude tokens. Use cloud agents when the Spark is busy.

## Supabase
- Project `usqwmybqjvldqjtaxsqi`, the same account as Learning Heaven. Schema `accnomos`, applied from `supabase/migrations/0001_accounts.sql`.
- RLS is on and only the service role can use it. The service key works; the publishable key is refused (401), as expected.

## Next steps, in order
1. Merge `paypal-direct` into `integ/wave3`, then `acc-ci integ/wave3` on the Spark and an independent review.
2. Build the PayPal plan provider (above) in PayPal **sandbox**. Read the PayPal hackathon rules first.
3. Hide the model names on the client side, and decide whether bring your own AI is in scope for the hackathon.
4. Fast-forward main once CI is green, deploy the API with the env changes above, and verify `/health`, `/account` and `/admin/ai-status`.
5. Record the self-employed video (`docs/video/SELF_EMPLOYED_SCRIPT.md`, Kokoro bf_emma, `tools/video/v3/tts.py`) on the Spark after the features are live. Show the bulk dump of zips and folders. Re-check it for Stripe wording.

## Owner to do
- PayPal developer account and sandbox app (client ID and secret go to the Spark via the clipboard script, never into chat).
- Make the repo private **after the 16 Nov community vote**. A reminder is set for 17 Nov 10:00, and the checklist is `docs/PRIVATE_REPO_CHECKLIST.md`.
- Apple Developer account (for TestFlight).
- HMRC production application (`docs/hmrc/PRODUCTION_APPLICATION.md`), which is needed for live VAT filing with users' own HMRC accounts.
- Stripe photo ID task.
- Decide what remote.gethits.co.uk is for. Don't expose Ollama publicly.
- Google Cloud projects stay under admin@zaytunauk.co.uk.

## Rules
- No secrets in the repo or in chat. Secrets go PC clipboard → ssh script → Spark `.env`, then clear the clipboard.
- Commit on non-main branches. Fast-forward main only after CI is green.
- UK English. No "coming soon/beta/launch" wording; the prelaunch-words check enforces it. Public text may name Anthropic but not "Claude" or other vendors (the guard is `tests/test_docs.py`). Use fictional demo data only.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
