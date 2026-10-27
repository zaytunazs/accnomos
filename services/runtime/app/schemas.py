"""Wire and domain schemas for document extraction and proposals.

`ExtractedDoc` is what the vision model returns. `extraction_json_schema()` turns
its pydantic schema into the *strict* JSON-schema dialect that both backends
accept (Meta Model API `strict: true` and Ollama `format`): every object closed
with `additionalProperties: false`, every property listed in `required`,
optionals expressed as `anyOf [..., null]`, no `$ref`/`oneOf`/`allOf`.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DocType = Literal["receipt", "purchase_invoice", "sales_invoice"]
PaymentMethod = Literal["card", "cash", "bank_transfer", "direct_debit", "cheque", "unknown"]
Severity = Literal["fail", "warn"]
Status = Literal["proposed", "needs_a_look"]
#: Lifecycle of a stored proposal: extraction decides proposed/needs_a_look, the user decides the rest.
ProposalStatus = Literal["proposed", "needs_a_look", "posted", "rejected"]

#: Categories offered to the model (also enforced as an enum in the JSON schema).
CATEGORIES: tuple[str, ...] = (
    "Tools & small equipment",
    "Materials",
    "Office supplies",
    "Motor expenses",
    "Travel",
    "Subsistence",
    "Software & subscriptions",
    "Telephone & internet",
    "Rent",
    "Utilities",
    "Insurance",
    "Professional fees",
    "Advertising",
    "Postage",
    "Bank charges",
    "Sales",
    "Sundry",
)


def _money(v: float) -> float:
    return round(float(v), 2)


class ExtractedLine(BaseModel):
    """One printed line item. Amounts in document currency, 2 dp."""

    description: str
    qty: float
    unit_price: float
    net: float
    vat_rate: float | None = Field(description="0, 5 or 20; null if not shown")
    vat: float

    @field_validator("unit_price", "net", "vat")
    @classmethod
    def _round_money(cls, v: float) -> float:
        return _money(v)


class ExtractedDoc(BaseModel):
    """Structured reading of one receipt or invoice."""

    doc_type: DocType
    supplier_name: str
    supplier_vat_number: str | None
    customer_name: str | None
    invoice_number: str | None
    date: str = Field(description="YYYY-MM-DD")
    currency: str = Field(description="ISO code, e.g. GBP")
    lines: list[ExtractedLine]
    net_total: float
    vat_total: float
    gross_total: float
    payment_method: PaymentMethod | None
    card_last4: str | None
    category_guess: str = Field(json_schema_extra={"enum": list(CATEGORIES)})
    confidence: float = Field(description="0-1 self-estimate")

    @field_validator("net_total", "vat_total", "gross_total")
    @classmethod
    def _round_money(cls, v: float) -> float:
        return _money(v)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.strip().upper() or "GBP"

    @field_validator("category_guess")
    @classmethod
    def _known_category(cls, v: str) -> str:
        return v if v in CATEGORIES else "Sundry"

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return min(1.0, max(0.0, float(v)))

    @field_validator("supplier_vat_number", "card_last4", "invoice_number", "customer_name")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v.strip() or None if isinstance(v, str) else v


class Check(BaseModel):
    code: str
    ok: bool
    severity: Severity
    message: str


class JournalLine(BaseModel):
    account: str
    debit_pence: int = 0
    credit_pence: int = 0
    vat_code: str | None = None


class AutopilotDecision(BaseModel):
    """What Autopilot decided for a proposal and why (app/autopilot.py)."""

    auto_approve: bool
    reasons: list[str]
    supplier_key: str | None = None


class Proposal(BaseModel):
    id: str
    doc_sha256: str
    extracted: ExtractedDoc
    checks: list[Check]
    status: ProposalStatus
    reasons: list[str]
    suggested_filename: str
    journal_draft: list[JournalLine]
    model: str
    elapsed_s: float
    # Set once the proposal lives in the user's books (_System/proposals/{id}.json).
    source_name: str | None = None  # original file name in "00 Inbox"
    file_path: str | None = None  # where the document is filed now
    account_override: str | None = None  # expense account chosen by a rule or the user
    created_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    event_id: str | None = None
    reject_reason: str | None = None
    autopilot: AutopilotDecision | None = None
    undone_events: list[str] = Field(default_factory=list)  # ledger events reversed by an undo, oldest first


# --------------------------------------------------------------------------- #
# Strict JSON schema
# --------------------------------------------------------------------------- #

_DROP_KEYS = {"title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "examples"}


def _is_nullable(s: dict[str, Any]) -> bool:
    if s.get("type") == "null":
        return True
    if isinstance(s.get("type"), list) and "null" in s["type"]:
        return True
    return any(_is_nullable(b) for b in s.get("anyOf", []))


def _strictify(node: Any, defs: dict[str, Any]) -> Any:
    """Recursively inline $refs, drop non-strict keywords and close objects."""
    if isinstance(node, list):
        return [_strictify(n, defs) for n in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        merged = {**copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
        return _strictify(merged, defs)

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROP_KEYS or key == "$defs":
            continue
        if key == "properties":
            out[key] = {p: _strictify(s, defs) for p, s in value.items()}
        else:
            out[key] = _strictify(value, defs)

    if out.get("type") == "object" or "properties" in out:
        props: dict[str, Any] = out.setdefault("properties", {})
        originally_required = set(node.get("required", []))
        for name, schema in props.items():
            if name not in originally_required and not _is_nullable(schema):
                props[name] = {"anyOf": [schema, {"type": "null"}]}
        out["type"] = "object"
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Strict JSON schema for any pydantic model, valid for both Ollama and Meta."""
    raw = model.model_json_schema()
    return _strictify(raw, raw.get("$defs", {}))


def extraction_json_schema() -> dict[str, Any]:
    """Strict JSON schema for `ExtractedDoc`, valid for both Ollama and Meta."""
    return strict_json_schema(ExtractedDoc)


# --------------------------------------------------------------------------- #
# Ask your books (POST /books/ask). Numbers come from code, words from the model.
# --------------------------------------------------------------------------- #

ASK_ANSWER_MAX = 1200
ASK_HISTORY_MAX = 6
AskActionKind = Literal["open_review", "open_vat", "chase_supplier", "none"]
Confidence = Literal["high", "medium", "low"]


class AskPeriod(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> AskPeriod:
        if self.end < self.start:
            raise ValueError("period end is before its start")
        return self


class AskTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    period: AskPeriod | None = None
    history: list[AskTurn] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _recent(cls, v: list[AskTurn]) -> list[AskTurn]:
        return v[-ASK_HISTORY_MAX:]


class KeyNumber(BaseModel):
    label: str
    value: str
    source: str


class SuggestedAction(BaseModel):
    label: str
    kind: AskActionKind
    arg: str | None


class AskModelOutput(BaseModel):
    """What the model returns. Length and count limits are enforced in code (strict mode rejects them)."""

    answer_md: str
    key_numbers: list[KeyNumber]
    citations: list[str]
    suggested_actions: list[SuggestedAction]
    confidence: Confidence


class AskAnswer(AskModelOutput):
    """The checked answer sent to the app."""

    model: str
    period: AskPeriod
    fallback_reason: str | None = None  # set when the model's words were replaced by the facts themselves
