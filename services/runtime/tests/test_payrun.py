"""PAYE pay runs (app/payrun.py): calculation per employee, year to date, and the proposal -> approve -> ledger flow."""

from __future__ import annotations

from datetime import date

import pytest

from accnomos_connectors import FakeStorageProvider
from app import approve as AP
from app import payrun as PR
from app.books import Books

USER = "owner@example.co.uk"


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


def employer(**kw: object) -> PR.EmployerSettings:
    base: dict[str, object] = {
        "name": "Acme Ltd",
        "paye_office": "123",
        "paye_reference": "AB45678",
        "accounts_office_ref": "123PA00045678",
    }
    return PR.EmployerSettings.model_validate({**base, **kw})


def ann(**kw: object) -> PR.Employee:
    base: dict[str, object] = {
        "payroll_id": "E001",
        "title": "Ms",
        "forenames": "Ann",
        "surname": "Lee",
        "nino": "AB123456C",
        "dob": date(1990, 5, 1),
        "gender": "F",
        "address": ["1 High St", "London"],
        "postcode": "SW16 1AA",
        "start_date": date(2020, 1, 1),
        "annual_salary_pence": 3_600_000,  # £3,000 a month
    }
    return PR.Employee.model_validate({**base, **kw})


async def setup(books: Books, *emps: PR.Employee, **settings: object) -> list[PR.Employee]:
    await PR.save_employer(books, employer(**settings), USER)
    for e in emps:
        await PR.save_employee(books, e, USER)
    return list(emps)


async def run_and_post(books: Books, pay_date: date, freq: str = "monthly") -> PR.PayRun:
    run = await PR.prepare(books, freq, pay_date, USER)  # type: ignore[arg-type]
    run, p = await PR.propose(books, run.id, USER)
    await AP.approve(books, p.id, USER)
    return await PR.get_run(books, run.id)


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #


def test_employee_validation() -> None:
    with pytest.raises(ValueError, match="National Insurance number"):
        ann(nino="XX123456Z")
    with pytest.raises(ValueError, match="B, E and I"):
        ann(ni_category="B")  # born 1990
    with pytest.raises(ValueError, match="workplace postcode"):
        ann(ni_category="F")
    with pytest.raises(ValueError, match="two lines of address"):
        ann(nino=None, address=["1 High St"])
    with pytest.raises(ValueError):
        ann(tax_code="ABC")
    assert ann(nino="ab 12 34 56 c").nino == "AB123456C"
    assert ann(tax_code="s1257l").code.prefix == "S"


async def test_payroll_ids_are_never_reused(books: Books) -> None:
    await setup(books, ann())
    with pytest.raises(PR.PayrunError, match="already used"):
        await PR.save_employee(books, ann(forenames="Other"), USER)


def test_starter_code_suggestions_are_marked_unverified() -> None:
    assert PR.suggested_starter_code("A")[:2] == ("1257L", False)
    assert PR.suggested_starter_code("B")[:2] == ("1257L", True)
    assert PR.suggested_starter_code("C")[:2] == ("BR", False)
    assert PR.suggested_starter_code(None)[:2] == ("0T", True)
    assert "new-employee-tax-code" in PR.suggested_starter_code("A")[2]


# --------------------------------------------------------------------------- #
# Calculation and year to date
# --------------------------------------------------------------------------- #


async def test_monthly_run_figures(books: Books) -> None:
    # £3,000 a month, 1257L month 7 cumulative from April with nothing paid before: free pay 7 x 1,048.26.
    await setup(books, ann(pension_exempt=True))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    (ln,) = run.lines
    assert (run.id, run.period, run.period_start, run.period_end) == (
        "2026-27-monthly-07",
        7,
        date(2026, 10, 6),
        date(2026, 11, 5),
    )
    assert ln.gross_pence == 300_000 and ln.taxable_pay_pence == 300_000
    assert ln.tax_pence == 0  # 3,000 < 7,337.82 free pay to date (no earlier months on this payroll)
    assert (ln.ee_ni_pence, ln.er_ni_pence) == (15_616, 38_745)  # (3,000 - 1,048) x 8%; (3,000 - 417) x 15%
    assert ln.net_pay_pence == 300_000 - 15_616
    assert run.status == "draft" and run.label == PR.ESTIMATE_NOTE


async def test_ytd_carries_across_posted_runs(books: Books) -> None:
    await setup(
        books,
        ann(pension_exempt=True, brought_forward=PR.BroughtForward(taxable_pay_pence=1_800_000, tax_pence=234_200)),
    )
    m7 = await run_and_post(books, date(2026, 10, 31))
    assert m7.lines[0].tax_pence == 39_040  # the spec's cumulative month 7 worked in test_paye
    m8 = await PR.prepare(books, "monthly", date(2026, 11, 30), USER)
    (ln,) = m8.lines
    assert ln.ytd.taxable_pay_pence == 2_400_000
    assert ln.ytd.tax_pence == 234_200 + 39_040 + ln.tax_pence
    assert ln.ytd.ni["A"].ee_pence == 2 * 15_616


async def test_earlier_unapproved_run_blocks_the_next(books: Books) -> None:
    await setup(books, ann(pension_exempt=True))
    await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    with pytest.raises(PR.PayrunConflict, match="earlier pay run"):
        await PR.prepare(books, "monthly", date(2026, 11, 30), USER)
    await PR.discard_run(books, "2026-27-monthly-07", USER)
    assert (await PR.prepare(books, "monthly", date(2026, 11, 30), USER)).period == 8


async def test_rates_only_for_2026_27(books: Books) -> None:
    await setup(books, ann())
    with pytest.raises(PR.PayrunError, match="2026-27"):
        await PR.prepare(books, "monthly", date(2027, 4, 30), USER)


async def test_edit_inputs_bonus_sick_maternity_and_deductions(books: Books) -> None:
    await setup(books, ann(pension_exempt=True))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    eid = run.lines[0].employee_id
    inputs = [
        PR.LineInputs(
            employee_id=eid,
            basic_pence=150_000,
            bonus_pence=20_000,
            sick=PR.SickPay(awe_pence=69_230, qualifying_days_per_week=5, days=3),
            maternity=None,
            deductions_after_tax_pence=5_000,
        )
    ]
    run = await PR.update(books, run.id, inputs, USER)
    (ln,) = run.lines
    assert ln.ssp_pence == 7_395  # 3 of 5 qualifying days at £123.25 a week (HMRC table)
    assert ln.gross_pence == 150_000 + 20_000 + 7_395
    assert ln.net_pay_pence == ln.gross_pence - ln.tax_pence - ln.ee_ni_pence - 5_000
    mat = [
        PR.LineInputs(
            employee_id=eid, basic_pence=0, maternity=PR.MaternityPay(awe_pence=69_230, first_week=1, weeks=4)
        )
    ]
    run = await PR.update(books, run.id, mat, USER)
    assert run.lines[0].smp_pence == 4 * 62_307  # 90% of £692.30, rounded up


async def test_hourly_pay(books: Books) -> None:
    await setup(books, ann(pay_type="hourly", hourly_rate_pence=1_271, usual_hours=86.75, pension_exempt=True))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    assert run.lines[0].basic_pence == 110_259  # 86.75 x £12.71 = £1,102.5925 -> £1,102.59


async def test_frequency_must_match(books: Books) -> None:
    await setup(books, ann(frequency="weekly", pension_exempt=True))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    assert run.lines == []  # nobody monthly-paid
    weekly = await PR.prepare(books, "weekly", date(2026, 10, 30), USER)
    assert weekly.period == 30 and weekly.lines[0].gross_pence == 69_231  # £36,000 / 52


async def test_student_loan_director_and_scottish(books: Books) -> None:
    await setup(
        books,
        ann(student_loan_plan="2", postgrad_loan=True, tax_code="S1257L", director=True, pension_exempt=True),
    )
    run = await PR.prepare(books, "monthly", date(2026, 4, 30), USER)
    (ln,) = run.lines
    assert ln.student_loan_pence == 4_900 and ln.postgrad_loan_pence == 7_500  # £49 plan 2; (3,000 - 1,750) x 6%
    assert ln.tax_code == "S1257L" and ln.tax_pence == 39_227
    # Director, annual earnings period: no employee NI until £12,570 to date; employer NI from £5,000 to date.
    assert ln.ee_ni_pence == 0 and ln.er_ni_pence == 0
    assert any("Director with a student loan" in w for w in ln.warnings)


async def test_leaver_and_payment_after_leaving(books: Books) -> None:
    await setup(books, ann(pension_exempt=True, leaving_date=date(2026, 10, 20)))
    run = await run_and_post(books, date(2026, 10, 31))
    assert run.lines[0].leaver
    later = await PR.prepare(books, "monthly", date(2026, 11, 30), USER)
    assert later.lines == []  # left before the period
    run2 = await PR.update(
        books, later.id, [PR.LineInputs(employee_id=run.lines[0].employee_id, basic_pence=50_000)], USER
    )
    ln = run2.lines[0]
    assert ln.payment_after_leaving and ln.tax_code == "0T W1/M1" and ln.tax_pence == 10_000


# --------------------------------------------------------------------------- #
# Pension in the pay run
# --------------------------------------------------------------------------- #


async def test_auto_enrolment_on_approval(books: Books) -> None:
    await setup(books, ann(annual_salary_pence=3_000_000))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    p = run.lines[0].pension
    assert (p.category, p.member, p.auto_enrolled_now) == ("eligible_jobholder", True, True)
    assert (p.employer_pence, p.employee_deducted_pence, p.opt_out_ends) == (5_940, 7_920, date(2026, 11, 30))
    assert (await PR.load_employees(books))[0].enrolled_on is None  # not until approved
    run, prop = await PR.propose(books, run.id, USER)
    await AP.approve(books, prop.id, USER)
    assert (await PR.load_employees(books))[0].enrolled_on == date(2026, 10, 31)


async def test_net_pay_and_salary_sacrifice_change_tax_and_ni(books: Books) -> None:
    await setup(books, ann(annual_salary_pence=3_000_000), pension={"arrangement": "net_pay"})
    ln = (await PR.prepare(books, "monthly", date(2026, 4, 30), USER)).lines[0]
    assert ln.ee_pension_net_pay_pence == 9_900 and ln.taxable_pay_pence == 250_000 - 9_900
    assert ln.ni_earnings_pence == 250_000  # net pay arrangement does not reduce NI
    await PR.save_employer(books, employer(pension={"arrangement": "salary_sacrifice"}), USER)
    run = await PR.prepare(books, "monthly", date(2026, 4, 30), USER)
    ln = run.lines[0]
    assert ln.salary_sacrifice_pence == 9_900 and ln.ni_earnings_pence == 250_000 - 9_900
    assert ln.pension.employer_pence == 5_940 + 9_900 and ln.ee_pension_from_net_pence == 0


async def test_opted_out_employee_is_not_a_member(books: Books) -> None:
    await setup(books, ann(enrolled_on=date(2026, 9, 30), opted_out_on=date(2026, 10, 15)))
    p = (await PR.prepare(books, "monthly", date(2026, 10, 31), USER)).lines[0].pension
    assert not p.member and any("refund" in n for n in p.notes)


# --------------------------------------------------------------------------- #
# Journal and the approve flow
# --------------------------------------------------------------------------- #


async def test_journal_balances_and_posts_only_on_approval(books: Books) -> None:
    await setup(books, ann(annual_salary_pence=3_000_000, student_loan_plan="2"))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    j = PR.journal(run)
    assert sum(x.debit_pence for x in j) == sum(x.credit_pence for x in j)
    accounts = {x.account for x in j}
    assert {
        PR.WAGES,
        PR.EMPLOYER_NI,
        PR.EMPLOYER_PENSION,
        PR.HMRC_LIABILITY,
        PR.PENSION_LIABILITY,
        PR.NET_WAGES,
    } <= accounts
    run, p = await PR.propose(books, run.id, USER)
    assert run.status == "proposed" and p.payroll_run == run.id and p.status == "proposed"
    assert await books.list_events() == []  # nothing posted yet
    with pytest.raises(AP.ApprovalError, match="calculated by code"):
        await AP.approve(books, p.id, USER, {"net_total": 1})
    posted = await AP.approve(books, p.id, USER)
    (ev,) = await books.list_events()
    assert ev.kind == "adjustment" and ev.proposal_id == p.id and ev.vat is None
    assert {ln.account for ln in ev.lines} == accounts
    assert (await PR.get_run(books, run.id)).status == "posted" and posted.status == "posted"


async def test_undo_and_reject_return_the_run(books: Books) -> None:
    await setup(books, ann(pension_exempt=True))
    run = await run_and_post(books, date(2026, 10, 31))
    await AP.undo(books, run.event_id or "", USER)
    run = await PR.get_run(books, run.id)
    assert run.status == "proposed" and run.event_id is None
    await AP.reject(books, run.proposal_id or "", USER, "wrong hours")
    run = await PR.get_run(books, run.id)
    assert run.status == "draft" and run.proposal_id is None
    run, p2 = await PR.propose(books, run.id, USER)  # a fresh proposal id, the old one stays rejected
    assert p2.id != (await books.list_proposals("rejected"))[0].id


async def test_back_to_draft_rejects_the_proposal(books: Books) -> None:
    await setup(books, ann(pension_exempt=True))
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    run, p = await PR.propose(books, run.id, USER)
    run = await PR.back_to_draft(books, run.id, USER)
    assert run.status == "draft" and (await books.get_proposal(p.id)).status == "rejected"


async def test_employment_allowance_reduces_employer_ni_cost(books: Books) -> None:
    await setup(books, ann(pension_exempt=True), claim_employment_allowance=True)
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    assert run.employment_allowance_pence == run.lines[0].er_ni_pence
    j = {x.account: x for x in PR.journal(run)}
    assert PR.EMPLOYER_NI not in j  # fully covered this month
    assert run.hmrc_due_pence == run.lines[0].tax_pence + run.lines[0].ee_ni_pence


def test_employment_allowance_cap() -> None:
    s = employer(claim_employment_allowance=True)
    assert PR.employment_allowance(s, 50_000, 1_040_000) == 10_000
    assert PR.employment_allowance(s, 50_000, 1_050_000) == 0
    assert PR.employment_allowance(employer(), 50_000, 0) == 0


async def test_cannot_delete_a_paid_employee(books: Books) -> None:
    (e,) = await setup(books, ann(pension_exempt=True))
    await run_and_post(books, date(2026, 10, 31))
    with pytest.raises(PR.PayrunConflict, match="leaving date"):
        await PR.delete_employee(books, e.id, USER)


def test_rti_test_switch_cannot_be_turned_on() -> None:
    with pytest.raises(ValueError):
        PR.EmployerSettings.model_validate({"rti_test_submission_enabled": True})
