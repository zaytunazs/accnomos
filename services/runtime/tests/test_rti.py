"""FPS and EPS XML (app/rti.py), validated against HMRC's 2026-27 schemas (tests/fixtures/hmrc_rti_2026_27, from the
"RTI RIM 2027 v1.0" pack on GOV.UK) with xmllint; plus P45, P60 and the employer payment record."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import defusedxml.ElementTree as DET
import pytest
from test_payrun import USER, ann, employer, run_and_post, setup  # sibling module: pytest puts tests/ on the path

from accnomos_connectors import FakeStorageProvider
from app import payrun as PR
from app import rti
from app.books import Books

SCHEMAS = Path(__file__).parent / "fixtures" / "hmrc_rti_2026_27"
FPS_XSD = SCHEMAS / "FullPaymentSubmission-2027-v1-0.xsd"
EPS_XSD = SCHEMAS / "EmployerPaymentSummary-2027-v1-0.xsd"
NS = {"f": rti.FPS_NS}


def validate(xml: bytes, xsd: Path, tmp_path: Path) -> None:
    if shutil.which("xmllint") is None:
        pytest.skip("xmllint is not installed: schema validation skipped (structure is still checked)")
    f = tmp_path / "doc.xml"
    f.write_bytes(xml)
    r = subprocess.run(["xmllint", "--noout", "--schema", str(xsd), str(f)], capture_output=True, text=True)  # noqa: S603, S607
    assert r.returncode == 0, r.stderr


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


async def fps_for(books: Books, pay_date: date = date(2026, 10, 31)) -> tuple[PR.PayRun, bytes]:
    run = await run_and_post(books, pay_date)
    emps = {e.id: e for e in await PR.load_employees(books)}
    return run, rti.build_fps(run, await PR.load_employer(books), emps)


def test_vendored_schemas_are_hmrc_2026_27() -> None:
    assert b"FullPaymentSubmission/26-27/1" in FPS_XSD.read_bytes()
    assert b"EmployerPaymentSummary/26-27/1" in EPS_XSD.read_bytes()


async def test_fps_validates_and_carries_the_figures(books: Books, tmp_path: Path) -> None:
    await setup(
        books,
        ann(student_loan_plan="2", start_date=date(2026, 6, 1), starter_declaration="A"),
        ann(
            payroll_id="E002", forenames="Bob Ray", surname="O'Neil", nino=None, gender="M", dob=date(2005, 2, 3),
            address=["2 Low Rd", "Croydon"], postcode="CR0 1AA", ni_category="M", tax_code="S1257L",
            director=True, director_appointed_on=date(2026, 9, 1), pension_exempt=True,
        ),
        ann(payroll_id="E003", forenames="Cy", surname="Jones", tax_code="C1257L M1", annual_salary_pence=1_200_000),
    )  # fmt: skip
    run, xml = await fps_for(books)
    validate(xml, FPS_XSD, tmp_path)
    root = DET.fromstring(xml)
    assert root.findtext("f:FullPaymentSubmission/f:RelatedTaxYear", namespaces=NS) == "26-27"
    assert root.findtext("f:IRheader/f:Keys/f:Key[@Type='TaxOfficeNumber']", namespaces=NS) == "123"
    emps = root.findall("f:FullPaymentSubmission/f:Employee", NS)
    assert len(emps) == 3
    by_id = {e.findtext("f:Employment/f:PayId", namespaces=NS): e for e in emps}
    a = by_id["E001"]
    assert a.findtext("f:Employment/f:Starter/f:StartDec", namespaces=NS) == "A"
    assert a.find("f:Employment/f:Payment/f:StudentLoanRecovered", NS).get("PlanType") == "02"  # type: ignore[union-attr]
    b = by_id["E002"]
    assert b.find("f:EmployeeDetails/f:NINO", NS) is None
    assert b.findtext("f:Employment/f:DirectorsNIC", namespaces=NS) == "AN"
    assert b.findtext("f:Employment/f:TaxWkOfApptOfDirector", namespaces=NS) == "22"
    code = b.find("f:Employment/f:Payment/f:TaxCode", NS)
    assert code is not None and code.text == "1257L" and code.get("TaxRegime") == "S"
    c = by_id["E003"].find("f:Employment/f:Payment/f:TaxCode", NS)
    assert c is not None and c.get("BasisNonCumulative") == "yes" and c.get("TaxRegime") == "C"
    line = next(ln for ln in run.lines if ln.payroll_id == "E001")
    ni = a.find("f:Employment/f:NIlettersAndValues", NS)
    assert ni is not None
    assert ni.findtext("f:TotalEmpNICInPd", namespaces=NS) == rti.money(line.er_ni_pence)
    assert ni.findtext("f:EmpeeContribnsInPd", namespaces=NS) == rti.money(line.ee_ni_pence)
    assert a.findtext("f:Employment/f:Payment/f:TaxDeductedOrRefunded", namespaces=NS) == rti.money(line.tax_pence)
    # The filing notice travels inside the file as a comment, and the file still validates with it.
    head = xml.split(b"\n", 2)[1].decode()
    assert head.startswith("<!-- NOT SUBMITTED TO HMRC.") and head.endswith(" -->")
    assert (
        "must be filed using HMRC's Basic PAYE Tools" in head
        and "Direct submission from Accnomos is not available" in head
    )


async def test_fps_for_a_leaver_and_final_submission(books: Books, tmp_path: Path) -> None:
    await setup(books, ann(leaving_date=date(2026, 10, 20), pension_exempt=True))
    run = await run_and_post(books, date(2026, 10, 31))
    emps = {e.id: e for e in await PR.load_employees(books)}
    xml = rti.build_fps(run, await PR.load_employer(books), emps, final_for_year=True)
    validate(xml, FPS_XSD, tmp_path)
    root = DET.fromstring(xml)
    assert root.findtext(".//f:LeavingDate", namespaces=NS) == "2026-10-20"
    assert root.findtext(".//f:FinalSubmission/f:ForYear", namespaces=NS) == "yes"


async def test_fps_needs_references_and_a_starter_declaration(books: Books) -> None:
    await setup(books, ann(start_date=date(2026, 6, 1), pension_exempt=True))
    run = await run_and_post(books, date(2026, 10, 31))
    emps = {e.id: e for e in await PR.load_employees(books)}
    with pytest.raises(rti.RtiError, match="starter declaration"):
        rti.build_fps(run, await PR.load_employer(books), emps)
    with pytest.raises(rti.RtiError, match="PAYE reference"):
        rti.build_fps(run, PR.EmployerSettings(), emps)


async def test_employer_payment_record_and_eps(books: Books, tmp_path: Path) -> None:
    await setup(books, ann(pension_exempt=True), claim_employment_allowance=True, small_employer_relief=True)
    run = await PR.prepare(books, "monthly", date(2026, 10, 31), USER)
    eid = run.lines[0].employee_id
    await PR.update(
        books,
        run.id,
        [PR.LineInputs(employee_id=eid, maternity=PR.MaternityPay(awe_pence=69_230, first_week=1, weeks=4))],
        USER,
    )
    run, p = await PR.propose(books, run.id, USER)
    from app.approve import approve

    await approve(books, p.id, USER)
    months = rti.employer_payment_record(await PR.list_runs(books), await PR.load_employer(books), date(2026, 4, 6))
    m7 = months[6]
    assert m7.smp_paid_pence == 249_228
    assert (m7.smp_recovered_pence, m7.nic_compensation_pence) == (249_228, 22_430)  # 100% + 9% (small employer)
    assert m7.due == date(2026, 11, 22)
    large = rti.employer_payment_record(await PR.list_runs(books), employer(), date(2026, 4, 6))[6]
    assert (large.smp_recovered_pence, large.nic_compensation_pence) == (229_289, 0)  # 92%, rounded down
    assert m7.due_pence == m7.tax_pence + m7.gross_ni_pence - 249_228 - 22_430 - m7.employment_allowance_pence
    eps = rti.build_eps(months, 7, await PR.load_employer(books), claim_employment_allowance=True)
    validate(eps, EPS_XSD, tmp_path)
    assert rti.FILE_NOTICE.encode() in eps.split(b"\n", 2)[1]
    root = DET.fromstring(eps)
    ns = {"e": rti.EPS_NS}
    assert root.findtext(".//e:EmpAllceInd", namespaces=ns) == "yes"
    assert root.findtext(".//e:RecoverableAmountsYTD/e:SMPRecovered", namespaces=ns) == "2492.28"
    # A month with no runs: "no payment for period" with the 6th-5th dates.
    eps5 = rti.build_eps(months, 5, await PR.load_employer(books))
    validate(eps5, EPS_XSD, tmp_path)
    assert DET.fromstring(eps5).findtext(".//e:NoPaymentDates/e:From", namespaces=ns) == "2026-08-06"
    # Paid, nothing to recover or claim: no EPS is needed.
    await PR.save_employer(books, employer(), USER)
    plain = rti.employer_payment_record(await PR.list_runs(books), await PR.load_employer(books), date(2026, 4, 6))
    plain[6].smp_paid_pence = plain[6].smp_recovered_pence = plain[6].nic_compensation_pence = 0
    with pytest.raises(rti.RtiError, match="No EPS is needed"):
        rti.build_eps(plain, 7, await PR.load_employer(books))


async def test_p45_and_p60_figures(books: Books) -> None:
    await setup(
        books,
        ann(pension_exempt=True, p45_previous_pay_pence=1_000_000, p45_previous_tax_pence=80_000),
        ann(payroll_id="E009", forenames="Lea", pension_exempt=True, leaving_date=date(2026, 10, 25)),
    )
    run = await run_and_post(books, date(2026, 10, 31))
    emps = {e.payroll_id: e for e in await PR.load_employees(books)}
    stay, leaver = emps["E001"], emps["E009"]
    ln_stay = next(x for x in run.lines if x.employee_id == stay.id)
    ln_left = next(x for x in run.lines if x.employee_id == leaver.id)
    p60 = rti.p60_figures(stay, ln_stay)
    assert p60.total_pay_pence == 1_000_000 + 300_000 and p60.previous_tax_pence == 80_000
    assert p60.this_employment_tax_pence == ln_stay.ytd.tax_pence
    p45 = rti.p45_figures(leaver, ln_left, run)
    assert (p45.leaving_date, p45.last_period, p45.tax_code) == (date(2026, 10, 25), "Month 7", "1257L")
    assert "Basic PAYE Tools" in p45.note
    with pytest.raises(rti.RtiError):
        rti.p45_figures(stay, ln_stay, run)


def test_money_format() -> None:
    assert (rti.money(0), rti.money(5), rti.money(-20_960), rti.money(123_456)) == (
        "0.00",
        "0.05",
        "-209.60",
        "1234.56",
    )
