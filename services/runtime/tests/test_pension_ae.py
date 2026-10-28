"""Auto-enrolment assessment, contributions and provider files (app/pension_ae.py).

Thresholds: TPR "Earnings thresholds" 2026-27 (monthly: lower £520, trigger £833, upper £4,189). Categories:
Pensions Act 2008 ss.1, 3 (eligible jobholder: at least 22, under State Pension age, earnings MORE than the trigger).
Minimums: employer 3 %, total 8 % of qualifying earnings (GOV.UK).
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app import pension_ae as AE

PAY_DAY = date(2026, 10, 31)


@pytest.mark.parametrize(
    ("dob", "earnings", "category"),
    [
        (date(1990, 1, 1), 83_301, "eligible_jobholder"),  # 36, £833.01 > trigger
        (date(1990, 1, 1), 83_300, "non_eligible_jobholder"),  # exactly the trigger is not "more than"
        (date(1990, 1, 1), 52_001, "non_eligible_jobholder"),
        (date(1990, 1, 1), 52_000, "entitled_worker"),  # at the lower level: no qualifying earnings
        (date(2005, 1, 1), 300_000, "non_eligible_jobholder"),  # 21: too young to enrol automatically
        (date(2004, 10, 31), 300_000, "eligible_jobholder"),  # 22 on the pay day
        (date(1959, 1, 1), 300_000, "non_eligible_jobholder"),  # over State Pension age (66 in 2025)
        (date(1951, 1, 1), 300_000, "not_a_worker"),  # 75
        (date(2011, 1, 1), 300_000, "not_a_worker"),  # 15
        (date(2010, 1, 1), 10_000, "entitled_worker"),  # 16
    ],
)
def test_assessment(dob: date, earnings: int, category: str) -> None:
    assert AE.assess(dob, PAY_DAY, earnings, "monthly").category == category


def test_trigger_boundary_is_flagged() -> None:
    a = AE.assess(date(1990, 1, 1), PAY_DAY, 83_300, "monthly")
    assert any("more than" in n for n in a.notes)


def test_weekly_thresholds() -> None:
    assert AE.assess(date(1990, 1, 1), PAY_DAY, 19_201, "weekly").category == "eligible_jobholder"
    assert AE.assess(date(1990, 1, 1), PAY_DAY, 12_000, "weekly").category == "entitled_worker"


def test_qualifying_earnings_relief_at_source() -> None:
    # £2,500: qualifying 2,500 - 520 = £1,980. Employer 3% = £59.40; employee 5% = £99.00 gross, £79.20 from pay.
    c = AE.contributions(AE.Scheme(), "monthly", 250_000)
    assert (c.base_pence, c.employer_pence, c.employee_gross_pence) == (198_000, 5_940, 9_900)
    assert (c.employee_deducted_pence, c.relief_claimed_by_scheme_pence, c.to_provider_pence) == (7_920, 1_980, 13_860)
    assert not c.warnings


def test_qualifying_earnings_capped_at_upper_level() -> None:
    c = AE.contributions(AE.Scheme(), "monthly", 600_000)
    assert c.base_pence == 418_900 - 52_000


def test_net_pay_and_salary_sacrifice() -> None:
    net = AE.contributions(AE.Scheme(arrangement="net_pay"), "monthly", 250_000)
    assert (net.employee_deducted_pence, net.relief_claimed_by_scheme_pence, net.sacrifice_pence) == (9_900, 0, 0)
    ss = AE.contributions(AE.Scheme(arrangement="salary_sacrifice"), "monthly", 250_000)
    assert (ss.sacrifice_pence, ss.employer_pence, ss.employee_deducted_pence) == (9_900, 5_940 + 9_900, 0)


def test_full_pay_basis_and_minimum_warning() -> None:
    full = AE.contributions(AE.Scheme(basis="full_pay"), "monthly", 250_000)
    assert full.base_pence == 250_000 and full.employer_pence == 7_500
    assert any("certify" in w for w in full.warnings)
    low = AE.contributions(AE.Scheme(employer_bp=200, employee_bp=500), "monthly", 250_000)
    assert any("minimum" in w for w in low.warnings)


def test_opt_out_window() -> None:
    assert AE.opt_out_ends(date(2026, 10, 31)) == date(2026, 11, 30)
    assert AE.opt_out_ends(date(2026, 1, 31)) == date(2026, 2, 28)


HEADER = AE.ScheduleHeader(
    date(2026, 10, 6), date(2026, 11, 5), date(2026, 10, 31), "monthly", "EMP123456789", "Ps 1", "AB12",
    date(2026, 11, 22),
)  # fmt: skip
ROW = AE.ScheduleRow(
    employee_id="e1", payroll_id="E001", title="Ms", forename="Ann Marie", surname="Lee", nino="AB123456C",
    dob=date(1990, 5, 1), gender="F", category="eligible_jobholder", pensionable_pence=198_000,
    employer_pence=5_940, employee_pence=7_920, employee_gross_pence=9_900, enrolled_on=date(2026, 10, 31),
    opted_out_on=None, left_on=None, gross_pay_pence=250_000, start_date=date(2026, 6, 1),
    address=("1 High St", "London"), postcode="SW16 1AA", email="ann@example.com",
)  # fmt: skip


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_nest_layout() -> None:
    r = rows(AE.nest_csv(HEADER, [ROW]))
    assert r[0] == ["H", "EMP123456789", "CS", "2026-11-05", "Ps 1", "2026-11-22", "Monthly", "", "", "2026-10-06", ""]
    assert r[1][:9] == ["D", "Lee", "AB123456C", "", "1980.00", "", "59.40", "79.20", ""]
    assert len(r[1]) == 21
    assert r[2] == ["T", "1", "4"]  # trailer: record count, Nest file version 4


def test_nest_reason_codes() -> None:
    left = AE.ScheduleRow(**{**ROW.__dict__, "left_on": date(2026, 10, 20)})
    out = AE.ScheduleRow(
        **{**ROW.__dict__, "opted_out_on": date(2026, 10, 15), "employer_pence": 0, "employee_pence": 0}
    )
    none = AE.ScheduleRow(**{**ROW.__dict__, "pensionable_pence": 0, "employer_pence": 0, "employee_pence": 0})
    later = AE.ScheduleRow(**{**ROW.__dict__, "left_on": date(2026, 12, 1)})  # leaves after this period
    r = rows(AE.nest_csv(HEADER, [left, out, none, later, ROW]))
    assert [x[8] for x in r[1:6]] == ["1", "9", "5", "", ""]
    assert r[6] == ["T", "5", "4"]


def test_peoples_pension_layout() -> None:
    r = rows(AE.peoples_pension_csv(HEADER, [ROW]))
    assert r[0] == ["H", "EMP123456789", "06/10/2026", "05/11/2026", "CO"]
    assert r[1] == AE.TPP_DETAIL_HEADINGS and r[1][0] == "Record Type"  # headings for the details section only
    assert r[2] == ["D", "01/05/1990", "E001", "59.40", "79.20", "", "", "1980.00"]
    assert r[3] == ["T", "138.60"]  # employer + employee


def test_peoples_pension_refused_characters_and_codes() -> None:
    odd = AE.ScheduleRow(**{**ROW.__dict__, "payroll_id": '=E"0[0]1!', "left_on": date(2026, 10, 31)})
    out = AE.ScheduleRow(**{**ROW.__dict__, "opted_out_on": date(2026, 10, 31)})
    low = AE.ScheduleRow(**{**ROW.__dict__, "pensionable_pence": 0})
    text = AE.peoples_pension_csv(HEADER, [odd, out, low])
    for ch in "=!'[]\"\\":
        assert ch not in text
    r = rows(text)
    assert r[2][2] == "E001" and [x[5] for x in r[2:5]] == ["1", "4", "5"]


def test_smart_pension_papdis() -> None:
    h = AE.ScheduleHeader(**{**HEADER.__dict__, "arrangement": "net_pay", "period_number": 7})
    net = AE.ScheduleRow(**{**ROW.__dict__, "employee_pence": 9_900})
    r = rows(AE.smart_pension_csv(h, [net]))
    assert len(r[0]) == 43 and r[0][0] == "PAPDIS Version" and r[0][42] == "Salary Sacrifice Indicator"
    assert all(len(x) == 43 for x in r)
    d = dict(zip(r[0], r[1], strict=True))
    assert (d["PAPDIS Version"], d["Pension Provider ID"], d["Employer ID"]) == (
        "PAP01",
        "Smart Pension",
        "EMP123456789",
    )
    assert (d["Pay Period Start Date"], d["Pay Period End Date"], d["Contribution Deduction Date"]) == (
        "2026-10-06",
        "2026-11-05",
        "2026-10-31",
    )
    assert (d["Frequency Code"], d["Tax Period"], d["Title"], d["Forename 1"], d["Forename 2"]) == (
        "M1",
        "07",
        "Ms",
        "Ann",
        "Marie",
    )
    assert (d["Birth Date"], d["Gender"], d["National Insurance Number"], d["Address 1"], d["Address 2"]) == (
        "1990-05-01",
        "F",
        "AB123456C",
        "1 High St",
        "London",
    )
    # enrolled on the pay date, inside this period: automatic enrolment event
    assert (d["Assessment Code"], d["Event Code"], d["Event Date"]) == ("1", "1", "2026-10-31")
    assert (d["Employer Contributions Amount"], d["Employee Contributions Amount"]) == ("59.40", "99.00")
    assert (d["Pensionable Earnings Amount"], d["Employer Contributions Percent"]) == ("1980.00", "3")
    assert (d["Employee Contributions Percent"], d["Salary Sacrifice Indicator"]) == ("5", "N")


def test_smart_pension_leaver_opt_out_and_sacrifice() -> None:
    h = AE.ScheduleHeader(**{**HEADER.__dict__, "arrangement": "salary_sacrifice", "period_number": 7})
    left = AE.ScheduleRow(**{**ROW.__dict__, "left_on": date(2026, 10, 20), "enrolled_on": date(2026, 4, 6)})
    out = AE.ScheduleRow(**{**ROW.__dict__, "opted_out_on": date(2026, 10, 15), "title": "Captain Sir"})
    sac = AE.ScheduleRow(**{**ROW.__dict__, "salary_sacrifice": True, "employer_pence": 15_840})
    r = rows(AE.smart_pension_csv(h, [left, out, sac]))
    a, b, c = (dict(zip(r[0], x, strict=True)) for x in r[1:4])
    assert (a["Exit Date"], a["Exit Reason Code"], a["Event Code"], a["Event Date"]) == ("2026-10-20", "1", "0", "")
    assert (b["AE Opt-Out Date"], b["Title"]) == ("2026-10-15", "")  # not one of Smart's accepted titles
    assert (c["Employee Contributions Amount"], c["Employer Contributions Amount"]) == ("0.00", "158.40")
    assert (c["Employer Contributions Percent"], c["Salary Sacrifice Indicator"]) == ("8", "Y")


def test_smart_pension_refuses_relief_at_source() -> None:
    h = AE.ScheduleHeader(**{**HEADER.__dict__, "arrangement": "relief_at_source"})
    with pytest.raises(AE.PensionFileError, match="net pay arrangement only"):
        AE.smart_pension_csv(h, [ROW])


def test_now_pensions_layout() -> None:
    r = rows(AE.now_pensions_csv(HEADER, [ROW], 7))
    assert len(r[0]) == 36 and r[0][0] == "Forename 1" and r[0][35] == "PENSIONABLE EARNINGS"
    d = dict(zip(r[0], r[1], strict=True))
    assert (d["Forename 1"], d["Forename 2"], d["SAL SACRIFICE"], d["EE CONTS"], d["ER CONTS"]) == (
        "Ann",
        "Marie",
        "N",
        "99.00",
        "59.40",
    )
    assert (d["ASSESSMENT"], d["PAYFREQ"], d["ER CODE"], d["PAY CODE"]) == (
        "Eligible jobholder",
        "Monthly",
        "EMP123456789",
        "AB12",
    )


def test_generic_csv_guards_formulas() -> None:
    evil = AE.ScheduleRow(**{**ROW.__dict__, "surname": "=HYPERLINK()"})
    text = AE.generic_csv(HEADER, [evil])
    assert "'=HYPERLINK()" in text
    assert rows(text)[0][0] == "Payroll ID"
