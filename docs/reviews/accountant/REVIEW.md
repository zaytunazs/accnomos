# Review: accountant collaboration and the Accountant portal

Branch `claude/accountant` (from `origin/main` at `9674a64`). A client invites their accountant by email, or opts in
to reviews by Accnomos accountants; the accountant signs in to a portal that lists every client's books shared with
them, opens one with the usual pages (view only, or edit if allowed), and leaves queries the client answers. No
database: access is OneDrive sharing, recorded in the client's own books. **Nothing in this branch has called
Microsoft Graph**; every sharing call ran against mocks built from the documented response shapes, or the test-mode fake.

## Sources (all read 28 Oct 2026)

| What | Source |
|---|---|
| `POST /drives/{d}/items/{i}/invite`: `recipients`, `roles` (`read` / `write`), `requireSignIn`, `sendInvitation`, `message` ≤ 2,000 chars; 200 or 207 (partial) with `permission` objects (`id`, `roles`, `invitation.email`); least privileged delegated scope **Files.ReadWrite** (personal and work); "Permissions can't be created or modified on the root driveItem of drives with a driveType of personal" | https://learn.microsoft.com/graph/api/driveitem-invite |
| `DELETE /drives/{d}/items/{i}/permissions/{perm-id}`, 204; only non-inherited permissions; Files.ReadWrite | https://learn.microsoft.com/graph/api/permission-delete |
| `GET /me/drive/sharedWithMe`, `remoteItem` with `parentReference.driveId`; `?allowexternal=true` for other tenants; needs a `*.All` scope to open the items; **"deprecated and will operate in a degraded state until November, 2026, after which it will stop returning data"** | https://learn.microsoft.com/graph/api/drive-sharedwithme |
| No documented replacement for `sharedWithMe` (Microsoft Q&A answers, not Microsoft docs) | https://learn.microsoft.com/answers/a/12909789, https://learn.microsoft.com/answers/a/12861830 |
| App folder: `Files.ReadWrite.AppFolder` gives access to `Apps/<app>`; "Your app's folder supports all the standard item operations" (sharing is not listed in its table) | https://learn.microsoft.com/onedrive/developer/rest-api/concepts/special-folders-appfolder |
| Path-based addressing relative to a shared folder's item id: "when working with shared folders, you can use a path-based URL relative to the shared folder's item ID"; `/drives/{drive-id}/items/{item-id}` | https://learn.microsoft.com/graph/onedrive-addressing-driveitems |
| `itemReference.driveId` + `id` address an item in another drive | https://learn.microsoft.com/graph/api/resources/itemreference |
| VAT return due one calendar month and seven days after the period (already in `app/deadlines.py`, VAT Notice 700/12; not re-checked here) | — |
| MTD for Income Tax quarterly update deadlines | **Not checked: gov.uk is blocked by this session's network policy, so these dates are not shown** |

**Can the personal app folder be shared?** By the documents, yes, with a `Files.ReadWrite` token: the only stated
restriction is on the drive's root item, and the app folder is a normal folder inside `Apps`. Not with the
`Files.ReadWrite.AppFolder` token the app uses for the books. So a personal account is asked for `Files.ReadWrite`
when (and only when) it invites someone. Fallbacks offered: share the folder yourself in OneDrive and record it
(`method: manual`, no Graph call), or a work account, whose books are the plain `/Accnomos` folder. A dedicated shared
folder (moving the books out of the app folder) was not built: it would mean moving the whole tree and every stored path.

## Design

* **Connectors** (`packages/connectors`): `GraphSharingProvider` (invite, revoke, sharedWithMe, folder, children,
  whoami) and `GraphStorageProvider(shared=SharedRoot)`, which addresses `/drives/{d}/items/{i}:/{path}` and creates
  folders under that drive, never under `/me`. Drive and item ids must match `[A-Za-z0-9!._~-]{1,256}`; paths still go
  through `_safe_path`. `invite`/`revoke` take a path inside the folder (`:/{path}:/invite`). `FakeSharingWorld` /
  `FakeSharingProvider` keep several people's drives and permissions, with inheritance downwards.
* **Roles.** `edit` = one `write` permission on the books folder. `read` = `read` on the folder **plus** `write` on
  `_System/queries`, so a view-only accountant can still leave queries. If the second grant fails the first is revoked.
* **Opening a client** (`app/sharing.py`, `routes_books.get_books`): three headers; the accountant's identity from Graph
  `/me` (cached by token hash); own cache key per (token, drive, item); `ReadOnlyStorage` for a view-only open, allowing
  only `_System/queries/`; no folder-rename migration; a Graph 403 there answers 403 instead of 401.
* **Audit.** `Books.audit` rewrites `user:` to `accountant:<verified email>` in shared books; a view-only accountant's
  lines go to `_System/queries/audit/` (their only writable place) and `GET /audit` reads them too.
* **Consent** for Accnomos accountants: five sentences (`accountant.CONSENT_TEXT`: who they are, what they see, view vs
  edit, never file or move money, how to stop and what stopping cannot undo), shown in full; the opt-in needs
  `agree: true` and the current `consent_version`; the record keeps the version and the sha256 of the exact text.
  `ACCOUNTANT_TEAM_EMAIL` empty: option hidden, route 404.
* **Portal.** `sharedWithMe` ∪ codes the accountant added (kept in their own `_System/Accountant/clients.json`), kept
  only when the folder holds `_System`; each summarised through its own read-only `Books`, four at a time; a client that
  stopped sharing shows "No longer shared with you." Sorted by the soonest VAT return.
* **Queries** (`app/queries.py`): one file per thread, ids `[0-9a-f]{12}` (never a path from input), If-Match updates,
  `waiting_on` computed. The client sees threads waiting on them on Home › To-dos; Review cards inside a client link
  to a new query about that card.
* **Web.** The open client lives in `sessionStorage` (this tab); `runtimeHeaders` adds the headers and asks for
  `Files.ReadWrite.All`; the portal asks for `Files.Read.All`; Settings › Your accountant and the portal always use your
  own books. `lib/graph.ts` reads follow the client; its writes refuse inside a client. A banner names whose books are open.
* **Android**: More › Your accountant, read-only.

## Tests

| Suite | Count | Result |
|---|---|---|
| `packages/connectors/tests/test_sharing.py` (new): invite body and URL, 207 partial failure, 403, revoke incl. already gone, sharedWithMe paging and filtering (files, unsafe ids), token never sent off Graph, books root personal/work, whoami, unsafe ids, shared-folder storage addressing, subfolder grants, fake inheritance | 14 | pass |
| `services/runtime/tests/test_accountant.py` (new): view-only and edit grants, email link, duplicate, validation, Graph refusal records nothing, half-invitation undone, revoke (and access lost), manual record, owner-only routes, profile, team hidden / consent required / opt-in / opt-out, portal summary, portal with sharedWithMe empty + codes, code checks, stopped sharing, code parsing, VAT deadline roll-over, same routes on client books, read-only refusal (incl. edit asked on view-only), edit audited as accountant, unshared folder / bad headers, query thread both sides, query ids never paths, audit sentences, cache isolation (immutable cache per client with one token), portal counts not leaking, read-only storage, 403 mapping, CORS preflight for the X-Books-* headers | 31 | pass |
| Runtime whole suite (`cd services/runtime && python -m pytest -q`) | see summary below | pass |
| Connectors whole suite | 63 | pass |
| `apps/web/e2e/accountant.spec.ts` (new): invite → listed → remove; consent box gates opt-in, stop; portal summary; open view-only → Review shows client's card → reject refused → query sent → back; add by code | 5 | pass |
| `apps/mobile/test/accountant_screen_test.dart` (new): access and threads at 360 dp with no edit controls, empty, error, More entry, parsing | 5 | pass |

## Risks

* Every Graph behaviour is from documents, not a live call: personal app-folder sharing with `Files.ReadWrite`, a write
  grant on a subfolder of a read-only share, cross-account-type sharing, Microsoft's invitation email.
* `sharedWithMe` stops in November 2026: after that the portal relies on codes added by hand.
* Asking a personal account for `Files.ReadWrite` widens the token for that call to the whole OneDrive; the UI says so
  and offers the manual route.
* Inside a client the browser holds a `Files.ReadWrite.All` token; what it may change is limited by the client's
  permission and the runtime's read-only guard, not by the token.
* The Entra app registration needs `Files.Read.All` and `Files.ReadWrite.All` as delegated permissions; not done here.
* `approved_by` on ledger events still comes from `X-User`; the audit line carries the verified identity.
* MTD for Income Tax deadlines are not in the portal (sources could not be reached).
* The portal reads every proposal of every client to count Review items (four clients at a time): slow for an
  accountant with many large books. Not measured.
* Found in self-review and fixed: the CORS allow-list lacked the three `X-Books-*` headers, which would have blocked
  every call inside a client in a real browser. The e2e suite could not see it (Playwright answers CORS preflights
  itself when it routes requests); `test_cors_lets_the_browser_send_the_client_headers` now covers it.
