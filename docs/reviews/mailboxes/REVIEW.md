# Review: more mailboxes for receipt intake

Branch `claude/mailboxes` (from `main` at 206848c). Outlook intake used to read only the signed-in account's mailbox.
Users can now link more Outlook.com / Microsoft 365 accounts and shared mailboxes; intake reads each one, copies a
file that reached two mailboxes once, and records which mailbox every document came from. Full behaviour:
`docs/INBOX.md` § "More than one mailbox".

## What changed

**Runtime** (commit `runtime: Outlook intake from several mailboxes`)
- `app/mailboxes.py` (new): the list in `_System/mail/mailboxes.json` (`id, address, kind, folder, allow_senders,
  deny_senders, added_at, added_by, last_scan_at, last_scan_saved, last_scan_error`); never a token. Kinds `primary`
  (always listed, stored only once changed or once other mailboxes exist), `microsoft`, `shared`. Validation of
  addresses, folders (no `/` or `\`, ≤100 chars) and sender lists (address or domain, ≤50); at most 10 extra
  mailboxes; writes go through `Books._update_json` (ETag); audit lines `mailbox_added/updated/removed`.
- `app/routes_mail.py`: `GET/POST /mail/mailboxes`, `PATCH/DELETE /mail/mailboxes/{id}` (writes need `X-User`;
  `shared` needs `X-Account-Kind: work`). `POST /mail/scan` takes `mailbox` (id); a linked mailbox needs its token in
  `X-Mailbox-Token` for that request. Graph 401/403 → 403, 404 → 404 ("mailbox or folder not found"), else 502, and the
  error is saved as the mailbox's `last_scan_error` (not on a dry run).
- Token handling: one mailbox per request (each token travels alone; also keeps under uvicorn/h11's ~16 KB header
  limit). `X-Mailbox-Token` added to `SECRET_HEADERS` and the scrub regex in `app/security.py` (8 KB cap, HTTPS-only
  behind a proxy, scrubbed from every log line) and to the CORS allow-list in `app/main.py`. Not accepted in a body:
  `StrictBody` would echo it in a 422.
- `packages/connectors`: `GraphMailProvider(token, mailbox=address)` reads `/users/{address}/…` (else `/me/…`);
  `list_messages` / `list_without_attachments` take `folder` (`None`/`all` as before, `inbox`, `archive`, or a top-level
  folder looked up once by `displayName`). `FakeMailProvider.add(..., folder=)`.
- `app/intake.py`: `scan_mail(..., mailbox=)` applies the mailbox's folder and sender lists (`filtered_senders` counted);
  seen-list keys are `(mailbox_id, message_id, attachment_id)` (old entries count as `primary`); de-dup by content hash
  is shared across mailboxes as before (seen.json + filed docs + 00 Inbox); `mailbox`/`mailbox_id` written to
  seen.json, the intake log, each result item and the `mail_scanned` audit line; last check saved on the mailbox.
- `app/inbox.py`: the Inbox scan maps each file's hash to the mailbox in seen.json and sets `Proposal.source_mailbox`
  and `mailbox` on the `proposed` audit line. `app/audit_view.py`: sentences for the new actions and the mailbox.
- `app/testmode.py`: a fake per linked address, seeded with one receipt the signed-in mailbox also has (gold 001) and
  one of its own (gold 033).

**Web** (commit `web: Settings › Email intake (more mailboxes)`)
- `components/settings/EmailIntake.tsx` (Settings › Automation, below Outlook intake; deep link `#email-intake`).
- `lib/msal.ts`: `signInExtraAccount` (`loginPopup`, `prompt: "select_account"`, scopes `["Mail.Read"]` only; re-sets
  the signed-in account as active before and after), `mailboxTokenSilent` (`acquireTokenSilent({scopes, account})`,
  never interactive), `forgetExtraAccount` (`clearCache({account})`), `primaryAccount`, `linkedAccount`.
- `lib/mailboxes.ts`: `checkAllMailboxes` — signed-in mailbox, then each linked one sequentially; one with no silent
  token is reported, not read. `OutlookIntake.tsx` shows the combined count and a line per mailbox.
- `lib/msal-test.ts`: the test build's fake now holds extra accounts (`loginPopup`, `getAllAccounts`, `clearCache`).
- Gmail: a disabled "Gmail (coming soon)" button and one line that it needs a Google Cloud app. Not built.

**Android** (commit `mobile 0.3.6+11 …`): `RuntimeClient.mailboxes()`; Settings › Automation lists the mailboxes
read-only under Outlook intake (address, kind, last check, count, last error) with a pointer to the web. The phone's
own check still reads only the signed-in mailbox.

**Docs**: `docs/INBOX.md` (new section, with Microsoft Learn citations for `Mail.Read.Shared` and
`/users/{id}/mailFolders('Inbox')/messages`), `docs/HONESTY.md` (untested against real mailboxes).

## Microsoft documentation checked (28 Oct 2026, Microsoft Learn)
- https://learn.microsoft.com/graph/outlook-share-messages-folders — shared/delegated mail is read with
  `GET users/{userId | userPrincipalName}/mailfolders('Inbox')/messages` under delegated `Mail.Read.Shared` or
  `Mail.ReadWrite.Shared`.
- https://learn.microsoft.com/graph/permissions-reference#mailreadshared — `Mail.Read.Shared`: delegated only, "Read
  user and shared mail", admin consent not required, "only valid for work or school accounts".
- https://learn.microsoft.com/graph/api/user-list-messages — `GET /users/{id | userPrincipalName}/messages` and
  `/users/{id}/mailFolders/{id}/messages`; `$orderby` must follow `$filter` (already respected).
- https://learn.microsoft.com/graph/api/resources/mailfolder — well-known names (`inbox`, `archive`, …) in any locale.

## Tests (run on Linux in this session)

| Gate | Result |
|---|---|
| `cd services/runtime && python -m pytest -q` | **1243 passed, 1 skipped** (was 1226 + 1 skipped on `main`; 17 new in `tests/test_mailboxes.py`) |
| `ruff check .` / `ruff format --check .` (0.17.3) | clean |
| `pyright services/runtime/app` (1.1.414) | 0 errors (whole repo also 0) |
| `pnpm install --frozen-lockfile && pnpm exec eslint .` | clean |
| `pnpm run e2e:build` | ok |
| `pnpm run e2e:test` | **222 passed, 4 failed of 226**; the 2 new tests in `e2e/email-intake.spec.ts` and `e2e/outlook.spec.ts` pass. The 4 failures fail identically on an unmodified `main` build in this container (checked in a separate worktree): see below |
| `flutter analyze` / `flutter test` (Flutter 3.47.8, downloaded to the scratchpad) | no issues / **265 passed** (2 new tests, 1 extended) |

New runtime tests (`tests/test_mailboxes.py`): sender filter matrix (7 cases); input normalisation; add/update/remove
with the stored file holding no token-like key and audit lines; **two mailboxes with the same attachment → copied
once, provenance in seen.json, the intake log and both `mail_scanned` audit lines, last check on the mailbox**; message
ids per mailbox; folder and allow/deny lists; **proposal `source_mailbox` and `proposed` audit `mailbox` after the Inbox
scan** (and none for a file dropped by hand); routes: link, 401 without `X-Mailbox-Token`, scan both, the shared mailbox
opened with the token sent for it, 404 for an unknown id, **no token in any stored file or captured log**; route
validation (no user, shared on a personal account, a `token` field refused with 422, bad folder, primary not removable);
scrubbing of the new header; Graph URLs for a shared mailbox, folder lookup once by name, quote escaping, and `/me`.

**The 4 e2e failures are this container, not the change:** the repo pins Playwright's `chromium_headless_shell-1248`,
which is not installed here, so the run used the preinstalled full Chromium 1243 through a local, uncommitted config
override. Its built-in PDF viewer requests `chrome-extension://…/pdf_embedder.css`, which the fixture's "nothing leaves
127.0.0.1" guard rejects (3 invoice tests), and its Tab order differs on `/vat` (`keyboard.spec.ts:135`). The same 4
fail on `origin/main` built and run the same way. CI (with the pinned browser) should be green; a human should confirm.

## Risks
- **Never run against real mailboxes or real MSAL.** Popups (blockers, the redirect bridge in every browser), a second
  account in the cache, `Mail.Read.Shared` consent in real tenants (some disable user consent), and folder lookup in a
  partly shared mailbox are untested.
- **Active account.** Many pages pick `getActiveAccount() ?? getAllAccounts()[0]`. The link flow sets the signed-in
  account active before and after the popup, and MSAL persists it, but a browser whose active account was never set
  could pick a linked account first. Not changed across the app.
- **Shared mailbox scope.** `Mail.Read.Shared` lets the app read any mailbox the user can open; the app only reads the
  addresses the user linked, but the consent screen grants more than that.
- **Dry run across mailboxes** lists a receipt twice (each mailbox previewed alone); the real check copies it once.
- **Duplicates are re-downloaded** on each check while in the window (unchanged behaviour, now possibly per mailbox).
- `Proposal.source_mailbox` is data only; the Review card does not show it yet.
- Only top-level folders can be watched by name.

## What a human must check
1. Sign in on accnomos.com with a personal account, *Add Microsoft mailbox* with a second Outlook.com account: the
   popup shows the account picker, consent lists only "Read your mail", the first account stays the one whose OneDrive
   holds the books (open Files), and *Check my inbox now* reads both.
2. With a Microsoft 365 work account that has full access to a shared mailbox: *Add shared mailbox*, consent to
   "Read user and shared mail", check it; then remove access in Exchange and confirm the row shows the error.
3. Sign out of the linked account (clear its cookies) and confirm the row says *Signed out in this browser* and the
   check reports it instead of failing.
4. Browser DevTools during a check: `X-Mailbox-Token` only on that mailbox's `/mail/scan` request; the runtime's logs
   show no token; `_System/mail/mailboxes.json` in OneDrive holds no token.
5. Remove a linked mailbox: its account is gone from MSAL's localStorage entries; copied files stay.
6. CI e2e with the pinned browser (the 4 container-only failures above).
7. Android: the list on a real phone at 360 dp against a real runtime.
