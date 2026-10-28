"""Your accountant: invite one by email, opt in to reviews by Accnomos accountants, take access back.

There is no Accnomos user database, so access *is* OneDrive sharing: an invitation shares the client's books folder
with the accountant's Microsoft account (Graph `driveItem: invite`), and revoking deletes that permission. What was
shared, with whom, when and on what terms is recorded in the client's own books, `_System/accountant.json`:

    {"invitations": [Invitation, ...], "profile": ClientProfile | null}

* **Roles.** `read` shares the folder with the Graph role `read` and adds a second permission, `write` on
  `_System/queries` only, so a view-only accountant can still leave queries. `edit` shares the folder with `write`.
* **Personal accounts.** The books live in the OneDrive app folder (`Apps/Accnomos`). Microsoft documents `invite`
  with `Files.ReadWrite` as the least privileged scope (not `Files.ReadWrite.AppFolder`), and refuses permissions
  only on a personal drive's *root* item; the app folder is not the root. So the web asks for `Files.ReadWrite` for
  this one call. Not yet tried against a real personal OneDrive (docs/HONESTY.md). If Microsoft refuses, the client
  can share the folder in OneDrive themselves and record it here (`method: "manual"`), or use a work account, whose
  books are the plain `/Accnomos` folder.
* **Accnomos accountants** (the operator's own team, `ACCOUNTANT_TEAM_EMAIL`; empty hides the option): a separate,
  explicit opt-in. The consent text below is shown in full; the client's agreement is stored with the version and a
  sha256 of the exact text. Withdrawing removes the permissions the same way.

Microsoft Learn, checked 28 Oct 2026: https://learn.microsoft.com/graph/api/driveitem-invite,
https://learn.microsoft.com/graph/api/permission-delete,
https://learn.microsoft.com/onedrive/developer/rest-api/concepts/special-folders-appfolder.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from accnomos_connectors.base import SharedRoot, SharingProvider
from app.books import QUERIES, SYSTEM, Books, now
from app.validation import StrictBody

ACCOUNTANT = f"{SYSTEM}/accountant.json"
TEAM_ENV = "ACCOUNTANT_TEAM_EMAIL"
WEB_ENV = "ACCNOMOS_WEB_URL"  # where the portal is, for the link in the invitation email (optional)

ClientKind = Literal["business", "sole_trader", "landlord", "personal"]
Role = Literal["read", "edit"]

EMAIL = re.compile(r"[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}")

#: Shown in full before the client opts in; the agreement records this version and the sha256 of these lines.
CONSENT_VERSION = "2026-10-28"
CONSENT_TEXT = (
    "Accnomos accountants are the accounting team of the people who run Accnomos. They are not your own "
    "accountant unless you also invite them as one.",
    "If you opt in, your Accnomos books folder in OneDrive is shared with the team's Microsoft account ({team}). "
    "They can see everything in it: your receipts and other documents, bank statements, invoices, your ledger, "
    "VAT figures, Books.xlsx and the audit trail.",
    "With 'View only' they can read all of it but change nothing, except that they can leave you queries "
    "(_System/queries). With 'View and edit' they can also approve, reject and correct entries; every change "
    "is recorded in your audit trail under their name.",
    "They never submit anything to HMRC for you and never move money.",
    "To stop, choose 'Stop reviews' in Settings › Your accountant: the sharing is removed at once. You can also "
    "remove it yourself in OneDrive (Manage access on the Accnomos folder). Copies they already downloaded are "
    "not removed by stopping.",
)


def team_email() -> str | None:
    """The Accnomos accountants' Microsoft account, or None when the operator has not set one (option hidden)."""
    raw = (os.getenv(TEAM_ENV) or "").strip().lower()
    return raw if raw and EMAIL.fullmatch(raw) else None


def consent_lines() -> list[str]:
    return [line.replace("{team}", team_email() or "the team's account") for line in CONSENT_TEXT]


def consent_sha256() -> str:
    return hashlib.sha256("\n".join(consent_lines()).encode()).hexdigest()


class AccountantError(ValueError):
    """The change is not possible as asked (duplicate invitation, unknown id, no consent)."""


class ClientProfile(StrictBody):
    """What the accountant portal shows about these books; written by the client, never inferred."""

    name: str = Field(default="", max_length=120)
    kind: ClientKind = "business"
    vat_registered: bool = True
    vat_start_month: int = Field(default=1, ge=1, le=12)  # a month a VAT period starts in (1: Jan/Apr/Jul/Oct)
    vat_months: Literal[1, 3] = 3


class Grant(BaseModel):
    """One Graph permission made for an invitation: on the folder ("") or on a path inside it."""

    id: str
    path: str = ""
    role: Literal["read", "write"]


class Consent(BaseModel):
    version: str
    text_sha256: str
    agreed_at: datetime
    agreed_by: str


class Invitation(BaseModel):
    id: str
    kind: Literal["own", "team"]
    email: str
    name: str = ""
    role: Role
    method: Literal["graph", "manual"]
    grants: list[Grant] = Field(default_factory=list)
    invited_at: datetime
    invited_by: str
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    consent: Consent | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class AccountantFile(BaseModel):
    invitations: list[Invitation] = Field(default_factory=list)
    profile: ClientProfile | None = None
    root: SharedRoot | None = None  # the books folder as Graph addresses it (from the first invitation)


class InviteIn(StrictBody):
    email: str = Field(max_length=254)
    name: str = Field(default="", max_length=120)
    role: Role = "read"
    method: Literal["graph", "manual"] = "graph"
    message: str = Field(default="", max_length=1000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL.fullmatch(v):
            raise ValueError("not an email address")
        return v


class TeamOptIn(StrictBody):
    agree: bool
    consent_version: str = Field(max_length=20)
    role: Role = "read"


class Settings(BaseModel):
    """GET /accountant: everything Settings › Your accountant shows."""

    invitations: list[Invitation]
    profile: ClientProfile | None
    team_available: bool
    team_email: str | None
    consent_version: str
    consent_text: list[str]
    client_code: str | None  # drive id:item id, for an accountant to add these books by hand in the portal


async def load(books: Books) -> AccountantFile:
    return AccountantFile.model_validate(await books.read_json(ACCOUNTANT, {}))


async def _save(books: Books, change) -> AccountantFile:  # noqa: ANN001 - a small local callback
    out: list[AccountantFile] = []

    def apply(raw: object) -> object:
        f = AccountantFile.model_validate(raw or {})
        change(f)
        out.append(f)
        return f.model_dump(mode="json")

    await books._update_json(ACCOUNTANT, {}, apply)
    return out[-1]


def client_code(root: SharedRoot | None) -> str | None:
    return f"{root.drive_id}:{root.item_id}" if root else None


async def settings(books: Books) -> Settings:
    f = await load(books)
    team = team_email()
    return Settings(
        invitations=sorted(f.invitations, key=lambda i: i.invited_at, reverse=True),
        profile=f.profile,
        team_available=team is not None,
        team_email=team,
        consent_version=CONSENT_VERSION,
        consent_text=consent_lines(),
        client_code=client_code(f.root),
    )


async def save_profile(books: Books, profile: ClientProfile, user: str) -> ClientProfile:
    def change(f: AccountantFile) -> None:
        f.profile = profile

    await _save(books, change)
    await books.audit(f"user:{user}", "accountant_profile_saved", {"kind": profile.kind})
    return profile


def _message(kind: str, who: str, root: SharedRoot, extra: str) -> str:
    code = client_code(root)
    web = (os.getenv(WEB_ENV) or "").rstrip("/")
    where = f"{web}/accountant?client={code}" if web else "the Accountant portal in Accnomos"
    lead = (
        f"{who} has opted in to reviews by Accnomos accountants and shared their Accnomos books with you."
        if kind == "team"
        else f"{who} has shared their Accnomos books with you."
    )
    tail = f"\n\n{extra.strip()}" if extra.strip() else ""
    return f"{lead}\n\nOpen them in {where}. Client code: {code}{tail}"


async def _grant(sharing: SharingProvider, root: SharedRoot, email: str, role: Role, message: str) -> list[Grant]:
    """The folder with `role`; for a view-only accountant also write on the queries folder (made if missing)."""
    first = await sharing.invite(root, email, "write" if role == "edit" else "read", message)
    grants = [Grant(id=first.id, role="write" if role == "edit" else "read")]
    if role == "read":
        try:
            q = await sharing.invite(root, email, "write", message, path=QUERIES)
        except Exception:
            await sharing.revoke(root, first.id)  # all or nothing: never leave half an invitation behind
            raise
        grants.append(Grant(id=q.id, path=QUERIES, role="write"))
    return grants


async def invite(
    books: Books,
    sharing: SharingProvider,
    account_kind: str,
    body: InviteIn,
    user: str,
    *,
    kind: str = "own",
    consent: Consent | None = None,
) -> Invitation:
    """Share the books and record it. `method: manual` records a share the client made in OneDrive themselves."""
    current = await load(books)
    if any(i.active and i.email == body.email for i in current.invitations):
        raise AccountantError(f"{body.email} already has access. Remove it first to change the access level.")
    root = current.root
    grants: list[Grant] = []
    if body.method == "graph":
        await books.storage.ensure_folder(QUERIES)  # the queries folder must exist before it can be shared
        root = await sharing.books_root(account_kind)
        grants = await _grant(sharing, root, body.email, body.role, _message(kind, user, root, body.message))
    inv = Invitation(
        id=uuid.uuid4().hex[:12],
        kind=kind,  # type: ignore[arg-type]
        email=body.email,
        name=body.name.strip(),
        role=body.role,
        method=body.method,
        grants=grants,
        invited_at=now(),
        invited_by=user,
        consent=consent,
    )

    def change(f: AccountantFile) -> None:
        f.invitations.append(inv)
        f.root = f.root or root

    await _save(books, change)
    action = "accountant_team_opted_in" if kind == "team" else "accountant_invited"
    await books.audit(f"user:{user}", action, {"email": body.email, "role": body.role, "method": body.method})
    return inv


async def revoke(
    books: Books, sharing: SharingProvider, account_kind: str, invitation_id: str, user: str
) -> Invitation:
    """Delete every permission the invitation made, then mark it revoked. KeyError for an unknown id."""
    current = await load(books)
    inv = next((i for i in current.invitations if i.id == invitation_id), None)
    if inv is None:
        raise KeyError(invitation_id)
    if not inv.active:
        return inv
    if inv.grants:
        root = current.root or await sharing.books_root(account_kind)
        for g in inv.grants:
            await sharing.revoke(root, g.id, g.path)  # already gone (removed in OneDrive) is fine
    revoked_at = now()

    def change(f: AccountantFile) -> None:
        for i in f.invitations:
            if i.id == invitation_id:
                i.revoked_at, i.revoked_by = revoked_at, user

    await _save(books, change)
    action = "accountant_team_opted_out" if inv.kind == "team" else "accountant_removed"
    await books.audit(f"user:{user}", action, {"email": inv.email, "method": inv.method})
    return inv.model_copy(update={"revoked_at": revoked_at, "revoked_by": user})


async def team_opt_in(
    books: Books, sharing: SharingProvider, account_kind: str, body: TeamOptIn, user: str
) -> Invitation:
    team = team_email()
    if team is None:
        raise LookupError("Reviews by Accnomos accountants are not offered on this server.")
    if not body.agree:
        raise AccountantError("Tick that you agree to the text above to opt in.")
    if body.consent_version != CONSENT_VERSION:
        raise AccountantError("The consent text has changed since you opened this page: read it again and opt in.")
    consent = Consent(version=CONSENT_VERSION, text_sha256=consent_sha256(), agreed_at=now(), agreed_by=user)
    invite_body = InviteIn(email=team, name="Accnomos accountants", role=body.role)
    return await invite(books, sharing, account_kind, invite_body, user, kind="team", consent=consent)


async def team_opt_out(books: Books, sharing: SharingProvider, account_kind: str, user: str) -> Invitation:
    current = await load(books)
    inv = next((i for i in current.invitations if i.kind == "team" and i.active), None)
    if inv is None:
        raise KeyError("team")
    return await revoke(books, sharing, account_kind, inv.id, user)
