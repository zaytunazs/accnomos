# Review: multiple profiles (branch `claude/profiles`)

One user can keep several companies, a sole-trader business and personal finances, each with separate books, and
switch between them. Built in three rounds; the owner changed the design twice while it was in progress.

## Design (as built)

1. **One Microsoft account is one profile.** The first plan (extra profiles as `Profiles/<slug>/` sub-folders of one
   OneDrive with an `X-Profile` header) was dropped on the owner's instruction before anything was committed. Now
   isolation comes from each profile's own Graph token: every request carries the selected account's
   `X-Graph-Token`/`X-Account-Kind` exactly as before, so the runtime needed little change and no new header.
2. **Linking, with no user database.** The web keeps every account signed in (MSAL multi-account cache:
   `getAllAccounts`, `setActiveAccount`, `loginRedirect` with `prompt: "select_account"`). Switching sets MSAL's
   active account (which `getToken`, and so every runtime and Graph call, already used) and reloads.
   `localStorage` `accnomos.profiles` (try/catch everywhere) remembers whose settings are live and each account's
   last-read name/kind/features for the menu.
3. **Per-business browser settings are kept per account.** The app keeps "the business" in many `localStorage`
   keys (business details, VAT period, Autopilot level, Ask history, intake/triage state, setup checklist, invoice
   draft). Without care, switching would send company A's VAT stagger and business name with company B's token.
   `apps/web/src/lib/profiles.ts` stashes those keys (`PROFILE_KEYS`) under the old account and restores the new one's
   on every switch; a page that loaded with the wrong copy reloads once. **The HMRC connection (sessionStorage) is
   dropped on every switch, never carried**, so a return can never be sent with another business's HMRC grant.
4. **What the books are** lives in each account's own `_System/profile.json`: name, kind (`company` | `sole_trader`
   | `personal`) and kind settings (company: company number, VAT number, VAT-registered; sole trader: UTR,
   accounting-year start MM-DD, VAT; personal: none), plus `linked` — the other accounts by sign-in name only (no
   tokens, no ids), so a new browser can offer "add your other accounts" (done: Settings › Business › Profile lists
   them). `GET`/`PUT /profile` (`services/runtime/app/profile.py`, `routes_profile.py`). No file = a VAT-registered
   company: existing users see no change.
5. **Kind gates features.** `features` on the profile; personal has no `vat`, `invoices`, `payroll`; `vat` needs
   `vat_registered`; `self_employment` only for sole traders. The runtime enforces it: 404 with a sentence on
   `/books/vat*`, `/books/deadlines`, `/reports/vat`, `/invoices/*`, `/credit-notes*`, `/payroll/*`
   (`routes_books.require_feature`, one read of profile.json on gated routes only). The web hides them.
6. **Xero-style menu bar** (signed in; `TopBar.tsx`, `ProfileMenu.tsx`, `lib/nav.ts`): profile switcher far left
   (linked profiles, *Add another account / business*, Settings); groups Home, Sales, Purchases, Reporting,
   Accounting, Tax, Payroll, Contacts, Personal (personal books only) as WAI-ARIA disclosure dropdowns; right: Search
   (find a page), Ask, Help, Notifications (Review count), account menu (email, AI in use, Profile details, *Sign out
   of this one*). Under 900 px the groups are in a modal `<dialog>` drawer. **A link shows only if its page exists in
   the build**: `lib/routes.server.ts` lists `src/app/**/page.tsx` at static-export time (AppShell is a server
   component), so pages other agents add appear automatically and nothing 404s. Signed out, the old sidebar and phone
   header are unchanged (sample pages rely on them).
7. **Caches never mix accounts.** Both cache layers were already keyed by a hash of the token; tests now prove it.
8. **Android**: the msal_auth setup is `account_mode: SINGLE` (`SingleAccountPca`). msal_auth has a
   `MultipleAccountPca`, but moving to it changes every token call and the config; not "clean" for this change. So
   the phone is one profile at a time: Settings shows "Profile: <name> · <kind>" and *Switch account* (sign out,
   forget the phone's business details, sign in).
9. **Test mode** gives a token `test-token.<account>` its own fake OneDrive/mail/calendar (`testmode.account_suffix`,
   keyed with the tenant). The web test sign-in (`msal-test.ts`) now holds several accounts: signing in while signed
   in adds Jo (`test-token.jo`). Plain `test-token` behaves exactly as before.

No profile delete anywhere: each profile is an account's own OneDrive; *Sign out of this one* only unlinks it here.

## What changed (commits)

- `f2fe418` runtime: `app/profile.py`, `app/routes_profile.py`, gates on VAT/invoice/credit-note/payroll routes,
  audit summary `profile_saved`, test-mode per-account fakes, `tests/test_profile.py`.
- `89ca767` web: `lib/profiles.ts`, `lib/nav.ts`, `lib/routes.server.ts`, `TopBar.tsx`, `ProfileMenu.tsx`,
  `settings/ProfileDetails.tsx`, Connect page *add another account* mode, multi-account test MSAL, nav gating in
  `AppNav.tsx`, `e2e/profiles.spec.ts`; existing specs updated where the sidebar is replaced by the menu bar
  (`home`, `keyboard`, `settings` "AI named" test now reads the account menu).
- `c5a5791` mobile: `RuntimeClient.booksProfile()`, `AppSettings.clearBusiness()`, Settings profile line and
  *Switch account*, `test/profile_switch_test.dart` (4 tests).
- `8492068` docs: ARCHITECTURE "Profiles (linked accounts)" + `_System/profile.json` row; HONESTY "Profiles".

## Tests

- Runtime: `pytest` 1243 passed, 1 skipped before the audit-summary fix (1 failure, fixed: `profile_saved` needed a
  summary); `test_profile.py` 17 passed (round trip, validation sentences, kind gating on 7 routes, two accounts'
  books and audit trails apart, cache keys and the immutable cache per account, token-suffix parsing).
  `ruff check`, `ruff format --check`, `pyright services/runtime/app`: clean (0 errors). See the final report for the
  last full run.
- Web: `eslint` 0 errors (1 pre-existing warning); `e2e/profiles.spec.ts` 3 passed (menu keyboard/aria/no-404 links;
  add Jo, set personal, gating in menu and runtime 404, switch back in one click with only that account's token on
  the wire; 360 px drawer with focus return and no sideways scroll). Full-suite result: see the final report (the
  machine was at load ~45 on 2 CPUs; many timeouts in an earlier run were folder creation still in progress).
- Android: not run here (no Flutter). Widget tests added mirroring `settings_groups_test.dart`.

## Risks

- Real MSAL multi-account has not been run: `logoutRedirect({account})` may end the Microsoft web session for other
  accounts too; consent per account; a personal and a work account side by side.
- The localStorage stash relies on `PROFILE_KEYS` being complete. A new per-business key added later must be added
  there, or it will leak across profiles. Two tabs on different profiles are not coordinated.
- Home's dashboard VAT tile is not gated (the menu hides VAT; the dashboard route answers for every kind).
- Customers/Suppliers menu items open the same Contacts page (no filter there yet).
- Android More screen does not hide VAT/invoices/payroll for personal books.
- The desktop layout for signed-in users changed (sidebar → top bar); screenshots in docs may be stale.

## What a human should check

1. Sign in with two real accounts (one personal, one work) on the web; switch; confirm Files and Review show each
   account's own OneDrive, and *Sign out of this one* leaves the other signed in.
2. Read `PROFILE_KEYS` in `apps/web/src/lib/profiles.ts` against every `localStorage` key the app writes.
3. Keyboard and a screen reader on the menu bar (disclosure groups, profile and account menus, the drawer at 360 px).
4. Run `flutter analyze` and `flutter test` in `apps/mobile` (new `test/profile_switch_test.dart`).
5. Decide whether the dashboard should hide its VAT tile for personal / non-VAT books.
