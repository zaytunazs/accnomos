"""FakeCalendarProvider: in-memory calendars, all-day events upserted by key."""

from __future__ import annotations

import pytest

from accnomos_connectors import FakeCalendarProvider

pytestmark = pytest.mark.asyncio


async def test_ensure_calendar_is_idempotent_and_upsert_replaces_by_key():
    cal = FakeCalendarProvider()
    cid = await cal.ensure_calendar("Accnomos")
    assert await cal.ensure_calendar("Accnomos") == cid
    assert await cal.ensure_calendar("Other") != cid

    ref = await cal.upsert_all_day_event(cid, "vat-26A3", "2026-11-07", "VAT return due", "first")
    assert await cal.upsert_all_day_event(cid, "vat-26A3", "2026-11-08", "VAT return due", "second") == ref
    assert cal.events[cid] == {"vat-26A3": ("2026-11-08", "VAT return due", "second")}


async def test_upsert_into_unknown_calendar_fails():
    with pytest.raises(FileNotFoundError):
        await FakeCalendarProvider().upsert_all_day_event("nope", "k", "2026-11-07", "t", "b")
