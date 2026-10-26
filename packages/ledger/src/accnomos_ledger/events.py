"""Ledger event model. Money is held in integer pence to avoid float drift."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class VatCode(StrEnum):
    """UK VAT treatment of a line. Rates are resolved by the VAT engine, not stored here."""

    STANDARD = "S"  # 20%
    REDUCED = "R"  # 5%
    ZERO = "Z"  # 0%, in Box 6/7
    EXEMPT = "E"  # outside the 9 boxes' VAT amounts, included in Box 6/7
    OUT_OF_SCOPE = "O"  # not on the return at all
    NO_VAT = "N"  # no VAT invoice held (e.g. cash parking); nothing reclaimed


class Line(BaseModel):
    account: str = Field(description="Account code, e.g. '5100 Tools & small equipment', '2200 VAT control'")
    debit: int = Field(0, ge=0, description="pence")
    credit: int = Field(0, ge=0, description="pence")
    vat_code: VatCode | None = None
    memo: str | None = None

    @model_validator(mode="after")
    def _one_side(self) -> "Line":
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("a line must have either a debit or a credit, not both or neither")
        return self


class LedgerEvent(BaseModel):
    """One immutable journal. Stored as Ledger/events/{yyyy-mm}/{ts}-{device}-{uuid}.json."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: Literal["purchase", "sale", "bank", "adjustment", "reversal"]
    date: date
    lines: list[Line] = Field(min_length=2)
    evidence: list[str] = Field(default_factory=list, description="document ids (sha256) backing this entry")
    approved_by: str = Field(description="user id/email who approved; agents never approve")
    approved_at: datetime
    proposal_id: str | None = None
    reverses: str | None = Field(None, description="id of the event this one reverses")
    net: int | None = Field(None, description="pence; the VAT-able net for sales/purchases")
    vat: int | None = Field(None, description="pence")
    counterparty: str | None = None

    @model_validator(mode="after")
    def _balanced(self) -> "LedgerEvent":
        debits = sum(line.debit for line in self.lines)
        credits = sum(line.credit for line in self.lines)
        if debits != credits:
            raise ValueError(f"unbalanced event: debits {debits} != credits {credits}")
        return self
