"""/profile: what these books are (app/profile.py), stored in the account's own `_System/profile.json`.

One Microsoft account is one profile, so there is no list here: the web keeps the linked accounts (MSAL's
multi-account cache plus a list in localStorage) and asks each account's books for its own profile.
Same headers as /books/*; saving also needs `X-User`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app import profile as profile_mod
from app.books import Books
from app.routes_books import business_name, get_books, require_user
from app.validation import StrictBody

router = APIRouter(tags=["profile"])


class ProfileBody(StrictBody):
    name: str = Field(min_length=1, max_length=80)
    kind: profile_mod.ProfileKind
    settings: dict[str, Any] | None = Field(default=None, max_length=10)
    linked: list[profile_mod.LinkedAccount] | None = Field(default=None, max_length=20)


@router.get("/profile", response_model=profile_mod.Profile)
async def get_profile(books: Books = Depends(get_books), business: str | None = Depends(business_name)) -> Any:
    """This account's profile; `exists: false` with the defaults (a VAT-registered company) when none is saved."""
    return await profile_mod.load(books, business or "")


@router.put("/profile", response_model=profile_mod.Profile)
async def put_profile(body: ProfileBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Any:
    """Save the whole profile. `linked` left out keeps the list already saved."""
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Give the profile a name.")
    settings = profile_mod.validate_settings(body.kind, body.settings)
    before = await profile_mod.load(books)
    linked = body.linked if body.linked is not None else (before.linked if before.exists else [])
    saved = profile_mod.Profile(
        name=name,
        kind=body.kind,
        settings=settings,
        linked=[a for a in linked if a.username.casefold() != user.casefold()],  # never itself
        updated_at=datetime.now(UTC),
        features=profile_mod.features_for(body.kind, settings),
    )
    await books.write_json(profile_mod.PROFILE, profile_mod.to_file(saved))
    await books.audit(
        f"user:{user}",
        "profile_saved",
        {"kind": body.kind, "kind_was": before.kind if before.exists else None, "linked": len(saved.linked)},
    )
    return saved
