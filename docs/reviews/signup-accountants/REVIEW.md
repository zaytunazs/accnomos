# Review: "Get 3 months free" in the submission build, and accountant copy

Branch `claude/signup-accountants` (from `main`, 29 Oct 2026). Owner's request: social posts (YouTube
https://youtu.be/SZiFWV_cX50) send people to accnomos.com for "3 months free", but the live site is the submission
build, where the early-adopter form rendered nothing. Pushed to `main` once every gate was green, as the owner asked
for this task.

## What changed

**Task 1: a neutral sign-up for the same list, in every build**

- Runtime (`services/runtime/app/early_access.py`): a second accepted consent wording, `SIGNUP_CONSENT_TEXT` =
  "Email me to set up my 3 months free of Accnomos. I can unsubscribe any time.", and `POST /public/sign-up`, the
  same handler as `/public/early-access` (same checks, rate limit, honeypot, `EARLY_ACCESS_ENABLED` switch and file).
  Each record stores the wording the person actually ticked. Why a second route: the submission build's export must
  hold no "early access" text in any file (CI, `scripts/prelaunch-words.mjs`), and the endpoint URL is a string in
  the JS bundle.
- Web: the form body moved into `components/sign-up/SignUpForm.tsx`, which takes its words and submit function as
  props. `JoinForm.tsx` is the neutral version (heading "Get 3 months free", the line "Leave your email and we will
  set you up with 3 months free.", same fields: email, optional name, business type, how you heard, consent);
  `EarlyAccessForm.tsx` is the pre-launch version, still folded out of a submission build. `lib/sign-up.ts` holds
  the shared types, the email check and the POST; `lib/early-access.ts` keeps only the launch wording and route.
- Placement: a hero link "Get 3 months free" next to "Try the demo" (to `#join`); the section near the end of the
  landing page (`#join`: the neutral form in the submission build, the pre-launch form in a `0` build, never both);
  the Pricing band (one line and the same link); a FAQ entry "How do I get 3 months free?"; a footer link; and
  `/join`, a short public page for the social posts (one paragraph on what Accnomos is, the form, the demo link).
  There is no `/pricing` route; pricing and the FAQ are sections of the landing page.
- Privacy (`/privacy#sign-up`): the list's section is now in every build, reworded without launch wording. The
  promises are the same: controller, what is collected, why, lawful basis (UK GDPR Art. 6(1)(a), PECR), where it is
  kept, deletion "by the end of November 2027" (what "12 months after launch" meant for a November 2026 launch),
  unsubscribe, ICO complaints. ICO guidance as checked in `docs/reviews/early-adopters/REVIEW.md` (28 Oct 2026); the
  consent stays unticked, specific to email, and names Accnomos, with the controller named under the button.
- The public chat's notes (`public_kb.md`) say how to get 3 months free and what the accountant options are.

**Task 2: accountant copy**

The landing page's "For accountants" section now spells out the two options, (a) invite your own accountant and
(b) opt in to a review by Accnomos accountants, links to Settings › Your accountant (`/settings#settings-accountant`)
and to the Accountant portal, and the FAQ has an expanded "Does my accountant need an account?" and a new "Can an
accountant review my books for me?". Every claim was checked against `app/accountant.py` (consent text, roles,
revoke) and `components/accountant/*`, `components/settings/YourAccountant.tsx` on main: view only or view and edit,
OneDrive sharing with their Microsoft account, queries on a transaction or document answered in Settings, edits
audited under the accountant's name, Stop reviews removes the sharing, never submits to HMRC or moves money. The
opt-in appears only when `ACCOUNTANT_TEAM_EMAIL` is set, so the copy says "where it is offered". The owner's word
"panel" is rendered as "our own accounting team", which is what the consent text says they are.

## Tests

- Runtime: `test_early_access.py` 44 (3 new: the neutral route feeds the same list with its own stored wording; the
  same refusals and honeypot; off with the list); `test_security_routes.py` lists the new public route with its
  reason. Full runtime suite: see the gate results below.
- e2e: new `e2e/sign-up.spec.ts`, 8 tests: hero link → form at 360 px, errors, sign-up stored with the neutral
  consent and source `/`; `/join` stores source `/join`; pricing, FAQ and footer links; a 503 is shown; axe on the
  form with errors showing; privacy section without launch words; mode `0` shows one form per page; the accountant
  section, its FAQ entries and the Settings link opening Your accountant for a signed-in owner. `/join` added to
  `e2e/pages.ts`, so the forbidden-words sweep (`submission-mode.spec.ts`), the phone smoke, axe and the signed-out
  link and button checks cover it. `early-access.spec.ts` now expects `/privacy#sign-up`.
- Production export: `pnpm build` then `node scripts/prelaunch-words.mjs out`: 345 files checked, 0 pre-launch
  phrases; no test-mode code.

## Gate results (merged with `origin/main` at 715c564, 29 Oct 2026)

| Gate | Result |
| --- | --- |
| `pytest -q` (services/runtime) | 2393 passed, 2 skipped |
| `ruff check .`, `ruff format --check .` | clean (586 files) |
| `pyright` | 0 errors |
| `eslint .`, `tsc --noEmit` | clean |
| `pnpm run e2e:build && pnpm run e2e:test` (`CI=1`) | 491 passed, 94 skipped (the opt-in screenshot specs `shots` and `design-shots`), 0 failed |
| `pnpm build` + `scripts/prelaunch-words.mjs out` | 345 files, 0 pre-launch phrases; no test-mode code |

One landing-page test reserves the words "to review" for app chrome; the first draft of the new FAQ answer said "opt
in … to reviews by" and was reworded.

## Risks

- The live runtime must have `EARLY_ACCESS_ENABLED=1` and its data volume; this cannot be seen from the repository.
  Without it the form says sign-ups are not open and gives the team's email address.
- "3 months free" is the operator's commitment; there is no billing in the product to enforce it.
- Sandbox note: this container's Chromium is build 1243 while the repo's Playwright 1.64.1 asks for 1248; the e2e
  run used the installed build through a local symlink (no repo change).
