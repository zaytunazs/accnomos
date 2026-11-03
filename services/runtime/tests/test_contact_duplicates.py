"""Possible duplicates by code: shared email/phone/VAT/close name, VAT conflicts, dismissals. No AI, no storage."""

from __future__ import annotations

from app import contacts as cb


def _contact(cid: str, name: str, **kw) -> cb.Contact:
    from app.autopilot import supplier_key

    key = kw.pop("normalised_key", None) or supplier_key(name)
    return cb.Contact(id=cid, kind="supplier", name=name, normalised_key=key, **kw)


def test_shared_email_phone_vat_and_name_all_link() -> None:
    a = _contact("a" * 16, "Screwfix", email="trade@screwfix.com")
    b = _contact("b" * 16, "SCREWFIX DIRECT LTD", email="Trade@Screwfix.com")
    (g,) = cb.find_duplicate_groups([a, b])
    assert g.contact_ids == ["a" * 16, "b" * 16] and not g.blocked
    assert "same email trade@screwfix.com" in g.evidence
    assert "names nearly the same: 'Screwfix' / 'SCREWFIX DIRECT LTD'" in g.evidence
    assert g.reason == "same email trade@screwfix.com"


def test_phone_normalised_to_uk_format() -> None:
    assert cb.normalise_phone("+44 117 496 0123") == "01174960123"
    assert cb.normalise_phone("0044 117 496 0123") == "01174960123"
    assert cb.normalise_phone("0117-496-0123") == "01174960123"
    assert cb.normalise_phone("(0117) 4960123") == "01174960123"
    assert cb.normalise_phone("123") is None
    assert cb.normalise_phone(None) is None
    a = _contact("a" * 16, "Howdens", phone="+44 117 496 0123")
    b = _contact("b" * 16, "Howdens Joinery", phone="0117 496 0123")
    (g,) = cb.find_duplicate_groups([a, b])
    assert "same phone 01174960123" in g.evidence


def test_same_vat_number_links_despite_names() -> None:
    a = _contact("a" * 16, "Acme", vrn="GB123456789")
    b = _contact("b" * 16, "Totally Different", vrn="GB 123 4567 89".replace(" ", ""))
    (g,) = cb.find_duplicate_groups([a, b])
    assert "same VAT number GB123456789" in g.evidence and not g.blocked


def test_same_name_across_different_vat_numbers_is_blocked() -> None:
    # "Smith Builders Ltd" normalises to the same key: hard evidence, but two VAT numbers means blocked.
    a = _contact("a" * 16, "Smith Builders", vrn="GB111111111")
    b = _contact("b" * 16, "Smith Builders Ltd", vrn="GB222222222")
    (g,) = cb.find_duplicate_groups([a, b])
    assert g.blocked
    assert "same normalised name smith-builders" in g.evidence
    assert "different VAT numbers: GB111111111, GB222222222" in g.evidence


def test_close_name_only_across_different_vat_numbers_is_no_candidate() -> None:
    # Only a shared word ("builders"), VAT numbers differ: two businesses, not a candidate.
    a = _contact("a" * 16, "Smith Builders", vrn="GB111111111")
    b = _contact("b" * 16, "Jones Builders", vrn="GB222222222")
    assert cb.find_duplicate_groups([a, b]) == []


def test_shared_email_with_vat_conflict_is_blocked() -> None:
    a = _contact("a" * 16, "Alpha", vrn="GB111111111", email="same@example.co.uk")
    b = _contact("b" * 16, "Beta", vrn="GB222222222", email="same@example.co.uk")
    (g,) = cb.find_duplicate_groups([a, b])
    assert g.blocked
    assert "different VAT numbers: GB111111111, GB222222222" in g.evidence
    assert "same email same@example.co.uk" in g.evidence


def test_email_domain_matching_name_is_evidence() -> None:
    a = _contact("a" * 16, "Someone Else", email="sales@screwfix.com")
    b = _contact("b" * 16, "Screwfix Direct", email="other@example.co.uk")
    (g,) = cb.find_duplicate_groups([a, b])
    assert any(e.startswith("email domain screwfix.com matches") for e in g.evidence)


def test_nothing_shared_is_no_candidate() -> None:
    a = _contact("a" * 16, "Howdens", email="a@example.co.uk")
    b = _contact("b" * 16, "Travis Perkins", email="b@example.co.uk")
    assert cb.find_duplicate_groups([a, b]) == []


def test_dismissed_pairs_are_never_suggested() -> None:
    a = _contact("a" * 16, "Screwfix", email="same@example.co.uk")
    b = _contact("b" * 16, "Screwfix Direct", email="same@example.co.uk")
    c = _contact("c" * 16, "Screwfix Trade", email="same@example.co.uk")
    assert len(cb.find_duplicate_groups([a, b, c])[0].contact_ids) == 3
    dismissed = {("a" * 16, "b" * 16), ("a" * 16, "c" * 16), ("b" * 16, "c" * 16)}
    assert cb.find_duplicate_groups([a, b, c], dismissed) == []
    # Dismissing one pair still leaves the other pair suggested.
    assert cb.find_duplicate_groups([a, b, c], {("a" * 16, "b" * 16)})[0].contact_ids == ["b" * 16, "c" * 16]


def test_transitive_grouping_collects_evidence() -> None:
    a = _contact("a" * 16, "Screwfix", email="same@example.co.uk")
    b = _contact("b" * 16, "Screwfix Direct", email="same@example.co.uk", phone="0117 496 0123")
    c = _contact("c" * 16, "Screwfix Trade Centre", phone="+44 117 496 0123")
    (g,) = cb.find_duplicate_groups([a, b, c])
    assert g.contact_ids == ["a" * 16, "b" * 16, "c" * 16]
    assert "same email same@example.co.uk" in g.evidence
    assert "same phone 01174960123" in g.evidence


def test_shared_place_or_trade_words_never_chain_into_one_group() -> None:
    # The Bramblewood mega-group: many businesses share one word each with a neighbour ("Northgate", "Interiors",
    # "Finch", "Energy", "& Sons"). None of them is the same business; none is suggested, and nothing chains.
    names = [
        "Northgate Civic Parking Ltd",
        "Halloway & Sons Interiors",
        "Thornfield Interiors Ltd",
        "Oak & Ash Interiors Ltd",
        "Northgate Transit Solutions Ltd",
        "Thornbury & Finch Books Ltd",
        "Harlow & Finch Interiors Ltd",
        "Northgate Energy Solutions Ltd",
        "Harrowgate Interiors",
        "Crimson Post & Parcel Ltd",
        "Northgate Premium Post Services Ltd",
        "Nimbus Home Energy Ltd",
        "Harrow & Finch Trading Ltd",
        "Havoc Hardware & Tools Ltd",
    ]
    contacts = [_contact(f"{i:016x}", n) for i, n in enumerate(names)]
    assert cb.find_duplicate_groups(contacts) == []


def test_close_names_are_pairs_never_chained() -> None:
    a = _contact("a" * 16, "Hargreaves & Sons Ironmongery")
    b = _contact("b" * 16, "Hargreaves & Son Hardware Ltd")
    c = _contact("c" * 16, "Hargreaves Hardware")
    d = _contact("d" * 16, "Halloway Joinery")
    e = _contact("e" * 16, "Holloway Joinery")  # a typo of d
    groups = cb.find_duplicate_groups([a, b, c, d, e])
    # a, b, c differ only by "& Son(s)" and hardware/ironmongery (one trade); d and e by one letter. Close names only
    # ever pair up: three pairs, never one chained group of three.
    assert [g.contact_ids for g in groups] == [
        ["a" * 16, "b" * 16],
        ["a" * 16, "c" * 16],
        ["b" * 16, "c" * 16],
        ["d" * 16, "e" * 16],
    ]
    assert (
        groups[0].reason == "names nearly the same: 'Hargreaves & Sons Ironmongery' / 'Hargreaves & Son Hardware Ltd'"
    )


def test_a_huge_hard_linked_set_is_shown_as_pairs() -> None:
    shared = [
        _contact(f"{i:016x}", f"Shop {chr(65 + i)}{chr(70 + i)}{chr(75 + i)}", email="all@example.co.uk")
        for i in range(8)
    ]
    groups = cb.find_duplicate_groups(shared)
    assert groups and all(len(g.contact_ids) == 2 for g in groups)
    assert len(groups) == 28  # every pair, each with its own evidence
