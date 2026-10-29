"""The set-up wizard (app/setup_wizard.py, app/routes_setup_wizard.py): rules, stops and the profile it writes.

Every inconsistent answer is covered: a VAT check naming another business stops the wizard until fixed or
explicitly confirmed; flat rate plus cash accounting stops it; turnover over the £90,000 VAT threshold without
registration warns; MTD Income Tax thresholds warn; bad UTR or company numbers are refused at the step.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import profile, testmode
from app import setup_wizard as wiz
from app.routes_profile import router as profile_router
from app.routes_setup_wizard import router as wizard_router

A = {"X-Graph-Token": "test-token", "X-User": "sam@sambuilds.example"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    monkeypatch.delenv("ACCNOMOS_TEST_AI_BASE", raising=False)
    app = FastAPI()
    for r in (testmode.router, profile_router, wizard_router):
        app.include_router(r)
    app.add_middleware(testmode.TenantMiddleware)
    c = TestClient(app, headers={testmode.TENANT_HEADER: "wizard"})
    assert c.post("/__test/reset", headers=A).json()["ok"]
    return c


def _drive() -> FakeStorageProvider:
    suffix = testmode.account_suffix({b"x-graph-token": b"test-token"})
    return testmode.STATES[f"wizard{suffix}"].storage


def _answer(client: TestClient, step: str, answers: dict) -> dict:
    r = client.put(f"/setup-wizard/step/{step}", headers=A, json={"answers": answers})
    assert r.status_code == 200, r.text
    return r.json()


def _company_flow(client: TestClient, name: str = "Sam Builds Ltd") -> dict:
    _answer(client, "business_type", {"business_type": "limited_company", "business_name": name})
    return _answer(
        client,
        "company",
        {
            "company_number": "01234567",
            "name": "SAM BUILDS LTD",
            "address": "1 High St, Leeds",
            "incorporation_date": "2020-01-01",
            "sic": "41200",
        },
    )


# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #


def test_names_match_ignores_ltd_and_case() -> None:
    assert wiz.names_match("Sam Builds Ltd", "SAM BUILDS LIMITED")
    assert wiz.names_match("Sam Builds", "Sam Builds Ltd")


def test_names_mismatch_is_a_stop() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "limited_company",
            "business_name": "Sam Builds Ltd",
            "vat": {
                "asked": True,
                "registered": True,
                "vat_number": "GB123456789",
                "scheme": "standard",
                "schemes": ["standard"],
                "period_start": "2026-04-01",
                "vat_check": {"registered": True, "name": "Acme Widgets plc"},
            },
        }
    )
    issues = wiz.evaluate(setup)
    assert [i.code for i in issues if i.blocking] == ["vat_name_mismatch"]
    assert not wiz.summary(setup)["can_continue"]


def test_explicit_acknowledgement_unblocks_but_is_recorded() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "limited_company",
            "business_name": "Sam Builds (trading name)",
            "vat": {
                "asked": True,
                "registered": True,
                "vat_number": "GB123456789",
                "scheme": "standard",
                "schemes": ["standard"],
                "period_start": "2026-04-01",
                "vat_check": {"registered": True, "name": "Sam Builds Holdings Ltd"},
                "mismatch_acknowledged": True,
            },
        }
    )
    assert wiz.summary(setup)["can_continue"]
    assert setup["vat"]["mismatch_acknowledged"] is True


# --------------------------------------------------------------------------- #
# Inconsistent choices
# --------------------------------------------------------------------------- #


def test_flat_rate_plus_cash_accounting_blocks() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "limited_company",
            "business_name": "Sam Builds Ltd",
            "vat": {
                "asked": True,
                "registered": True,
                "vat_number": "GB123456789",
                "scheme": "flat_rate",
                "schemes": ["flat_rate", "cash"],
                "period_start": "2026-04-01",
                "flat_rate": {"sector": "Photography"},
            },
        }
    )
    assert [i.code for i in wiz.evaluate(setup) if i.blocking] == ["flat_rate_cash"]


def test_turnover_over_vat_threshold_unregistered_warns() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "sole_trader",
            "business_name": "Sam",
            "vat": {"asked": True, "registered": False},
            "income_tax": {"asked": True, "turnover_pence": 95_000_00},
        }
    )
    codes = [i.code for i in wiz.evaluate(setup)]
    assert "vat_threshold" in codes
    assert wiz.summary(setup)["can_continue"]  # a warning, not a stop


def test_turnover_below_vat_threshold_is_quiet() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "sole_trader",
            "business_name": "Sam",
            "vat": {"asked": True, "registered": False},
            "income_tax": {"asked": True, "turnover_pence": 40_000_00},
        }
    )
    assert "vat_threshold" not in [i.code for i in wiz.evaluate(setup)]


def test_mtd_itsa_thresholds() -> None:
    def codes_for(turnover_pence: int) -> list[str]:
        setup = wiz.blank_setup()
        setup.update(
            {
                "business_type": "sole_trader",
                "business_name": "Sam",
                "income_tax": {"asked": True, "turnover_pence": turnover_pence},
            }
        )
        return [i.code for i in wiz.evaluate(setup)]

    assert "mtd_itsa_2026" in codes_for(60_000_00)
    assert "mtd_itsa_2027" in codes_for(35_000_00)
    assert not ([c for c in codes_for(20_000_00) if c.startswith("mtd_")])


def test_limited_cost_trader_flagged() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "sole_trader",
            "business_name": "Sam",
            "vat": {
                "asked": True,
                "registered": True,
                "vat_number": "GB123456789",
                "scheme": "flat_rate",
                "schemes": ["flat_rate"],
                "period_start": "2026-04-01",
                "flat_rate": {"sector": "Photography", "relevant_goods_share_pct": 1.5, "limited_cost": False},
            },
        }
    )
    assert "limited_cost_trader" in [i.code for i in wiz.evaluate(setup)]


def test_bad_paye_reference_warns() -> None:
    setup = wiz.blank_setup()
    setup.update(
        {
            "business_type": "limited_company",
            "business_name": "Sam Builds Ltd",
            "payroll": {"asked": True, "has_employees": True, "paye_reference": "not-a-ref"},
        }
    )
    assert "paye_format" in [i.code for i in wiz.evaluate(setup)]


# --------------------------------------------------------------------------- #
# Steps over HTTP: validation, save-as-you-go, summary
# --------------------------------------------------------------------------- #


def test_business_type_step_needs_a_name(client: TestClient) -> None:
    r = client.put("/setup-wizard/step/business_type", headers=A, json={"answers": {"business_type": "personal"}})
    assert r.status_code == 400


def test_personal_books_skip_to_summary(client: TestClient) -> None:
    got = _answer(client, "business_type", {"business_type": "personal", "business_name": "Jo at home"})
    assert got["steps"] == ["business_type", "summary"]
    assert got["current_step"] == "summary"
    assert got["returns"] == [{"return": "Nothing to file", "when": "Personal books keep budgets and spending only."}]


def test_company_step_validates_number(client: TestClient) -> None:
    _answer(client, "business_type", {"business_type": "limited_company", "business_name": "Sam Builds Ltd"})
    r = client.put("/setup-wizard/step/company", headers=A, json={"answers": {"company_number": "12"}})
    assert r.status_code == 400


def test_utr_must_be_ten_digits(client: TestClient) -> None:
    _answer(client, "business_type", {"business_type": "sole_trader", "business_name": "Sam"})
    r = client.put("/setup-wizard/step/income_tax", headers=A, json={"answers": {"utr": "abc"}})
    assert r.status_code == 400


def test_sole_trader_defaults_to_cash_basis(client: TestClient) -> None:
    _answer(client, "business_type", {"business_type": "sole_trader", "business_name": "Sam"})
    got = _answer(client, "income_tax", {"utr": "1234567890", "turnover_pence": 40_000_00})
    assert got["setup"]["income_tax"]["accounting_basis"] == "cash"


def test_full_company_flow_confirms_and_writes_profile(client: TestClient) -> None:
    _company_flow(client)
    _answer(
        client,
        "vat",
        {
            "registered": True,
            "vat_number": "GB123456789",
            "scheme": "standard",
            "period_start": "2026-04-01",
            "vat_check": {"registered": True, "name": "Sam Builds Ltd", "consultation_number": "C1"},
        },
    )
    _answer(client, "income_tax", {"turnover_pence": 40_000_00})
    _answer(client, "cis", {"is_subcontractor": False, "is_contractor": False})
    _answer(client, "payroll", {"has_employees": False})
    status = client.get("/setup-wizard", headers=A).json()
    assert status["current_step"] == "summary"
    assert status["can_continue"] is True

    confirmed = client.post("/setup-wizard/confirm", headers=A).json()
    assert confirmed["filed"] == []
    assert "Nothing is filed" in confirmed["filing_note"]
    assert confirmed["profile"]["kind"] == "company"
    assert confirmed["profile"]["settings"]["company_number"] == "01234567"

    on_disk = json.loads(_drive().files[profile.PROFILE])
    assert on_disk["kind"] == "company"
    assert on_disk["setup"]["company"]["number"] == "01234567"
    assert on_disk["setup"]["confirmed_at"]


def test_confirm_refuses_a_blocking_mismatch(client: TestClient) -> None:
    _company_flow(client)
    _answer(
        client,
        "vat",
        {
            "registered": True,
            "vat_number": "GB999999999",
            "scheme": "standard",
            "period_start": "2026-04-01",
            "vat_check": {"registered": True, "name": "Someone Else Ltd"},
        },
    )
    r = client.post("/setup-wizard/confirm", headers=A)
    assert r.status_code == 400
    assert "vat" in r.json()["detail"].lower() or "VAT" in r.json()["detail"]
