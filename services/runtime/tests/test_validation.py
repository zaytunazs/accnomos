"""Input validation: file names cannot climb out of the user's folder, POST bodies are strict, keys are checked.

Contact VRN format: tests/test_contacts.py (edit errors). Relay VRN/period key: hmrc-relay tests."""

from __future__ import annotations

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.msgraph import GraphStorageProvider
from fastapi.testclient import TestClient

from app.books import Books
from app.main import app
from app.pipeline import suggested_filename
from app.routes_books import get_books
from app.schemas import ExtractedDoc
from app.validation import UnsafeName, check_name

H = {"X-Graph-Token": "t", "X-User": "sam@example.com"}


@pytest.fixture
def tc():
    books = Books(FakeStorageProvider())

    async def _books():
        yield books

    app.dependency_overrides[get_books] = _books
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- file names ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["statement.csv", "Barclays Oct 2026.csv", "a..b.csv", "£38.47 receipt.jpg", ".hidden"])
def test_plain_names_pass(name):
    assert check_name(name) == name


@pytest.mark.parametrize("name", [
    "", ".", "..", "...", " .. ", "../x.csv", "..\\x.csv", "a/b.csv", "/etc/passwd", "\\\\server\\share",
    "C:\\Users\\x.csv", "c:x.csv", "x\x00.csv", "x\n.csv", "x\x1b[31m.csv", "x\x7f.csv", "a" * 201,
])
def test_unsafe_names_refused(name):
    with pytest.raises(UnsafeName):
        check_name(name)


@pytest.mark.parametrize("name", ["..", "../../escape.csv", "/abs.csv"])  # multipart itself drops NULs, C:\ prefixes
def test_bank_import_refuses_unsafe_file_names(tc, name):
    r = tc.post("/books/bank/import", headers=H, files={"file": (name, b"Date,Amount\n", "text/csv")})
    assert r.status_code == 400 and "file name" in r.json()["detail"]


async def test_free_path_is_the_backstop():
    books = Books(FakeStorageProvider())
    with pytest.raises(UnsafeName):
        await books.free_path("03 Bank statements/2026-10", "..")


def test_model_output_cannot_put_a_path_in_the_filed_name():
    doc = ExtractedDoc(
        doc_type="receipt", supplier_name="../../Documents/x", supplier_vat_number=None, customer_name=None,
        invoice_number=None, date="../../../Desktop", currency="/../", lines=[], net_total=1, vat_total=0,
        gross_total=1, payment_method=None, card_last4=None, category_guess="Sundry", confidence=0.5,
    )
    name = suggested_filename(doc, "image/jpeg")
    assert check_name(name) == name and "/" not in name and ".." not in name


@pytest.mark.parametrize("path", ["..", "a/../b", "a/./b", "x\x00", "proposals/ ../x"])
def test_graph_provider_refuses_unsafe_paths(path):
    with pytest.raises(ValueError, match="unsafe storage path"):
        GraphStorageProvider("t")._item_url(path)


def test_graph_provider_accepts_normal_paths():
    url = GraphStorageProvider("t")._item_url("_System/proposals/abc.json", "content")
    assert url.endswith("approot:/_System/proposals/abc.json:/content")


# --- strict bodies, keys --------------------------------------------------------------------------------------

@pytest.mark.parametrize(("method", "path", "body"), [
    ("post", "/books/ask", {"question": "How much VAT?", "admin": True}),
    ("post", "/books/proposals/abcdef12/reject", {"reason": "dup", "status": "posted"}),
    ("post", "/books/approve/abcdef12", {"edits": {}, "user": "someone-else"}),
    ("post", "/books/bank/lines/0123456789abcdef/match", {"event_id": "abc", "extra": 1}),
    ("post", "/jobs", {"name": "Kitchen", "status": "open", "id": "chosen-by-client"}),
    ("post", "/staff", {"name": "Al", "hourly_rate_pence": 1500, "is_admin": True}),
    ("post", "/timesheets", {"staff_id": "s", "job_id": "j", "date": "2026-10-01", "hours": 1, "rate": 99}),
    ("put", "/contacts/0123456789abcdef", {"name": "Acme", "id": "other"}),
    ("post", "/contacts/import-outlook", {"add_new": True, "x": 1}),
    ("post", "/mail/scan", {"since_days": 7, "folder": "../"}),
    ("post", "/ai/test", {"mode": "local", "api_key": "leak"}),
])
def test_unknown_fields_are_rejected(tc, method, path, body):
    r = getattr(tc, method)(path, headers=H, json=body)
    assert r.status_code == 422, r.text
    assert any(e["type"] == "extra_forbidden" for e in r.json()["detail"])


def test_over_long_free_text_is_rejected(tc):
    assert tc.post("/books/proposals/abcdef12/reject", headers=H, json={"reason": "x" * 1001}).status_code == 422


@pytest.mark.parametrize("key", ["26A", "26A33", "../x", "26 3", "%2e%2e"])
def test_vat_period_key_format(tc, key):
    assert tc.get("/books/vat", headers=H, params={"period_key": key}).status_code == 422


def test_vat_period_key_accepts_hmrc_shapes(tc):
    for key in ("26A3", "18AD", "#001"):
        assert tc.get("/books/vat", headers=H, params={"period_key": key, "start": "2026-07-01",
                                                       "end": "2026-09-30"}).status_code == 200
