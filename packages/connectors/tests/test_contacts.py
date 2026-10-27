"""GraphContactsProvider against httpx.MockTransport (no network)."""

from __future__ import annotations

import httpx
import pytest

from accnomos_connectors.msgraph import GraphContactsProvider, GraphError

pytestmark = pytest.mark.asyncio

NEXT = "https://graph.microsoft.com/v1.0/me/contacts?page=2"


def _provider(handler) -> GraphContactsProvider:
    async def sleep(_s: float) -> None:
        return None

    return GraphContactsProvider("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=sleep)


async def test_list_contacts_select_paging_and_mapping():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET" and req.headers["Authorization"] == "Bearer tok"
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"value": [{"id": "c3", "displayName": "Jo Bloggs"}]})
        return httpx.Response(
            200,
            json={
                "@odata.nextLink": NEXT,
                "value": [
                    {
                        "id": "c1",
                        "displayName": " Sam Patel ",
                        "companyName": "Acme Kitchens Ltd",
                        "emailAddresses": [{"name": "Sam", "address": "sam@acme.example"}, {"address": ""}],
                        "businessPhones": ["020 7946 0000", " "],
                    },
                    {
                        "id": "c2",
                        "displayName": "Howdens",
                        "companyName": None,
                        "emailAddresses": [],
                        "businessPhones": [],
                    },
                ],
            },
        )

    out = await _provider(handler).list_contacts()
    assert seen[0].url.path == "/v1.0/me/contacts"
    assert seen[0].url.params["$select"] == "displayName,emailAddresses,businessPhones,companyName"
    assert "$select" not in seen[1].url.params  # the nextLink is followed as-is
    assert [c.id for c in out] == ["c1", "c2", "c3"]
    assert out[0].display_name == "Sam Patel" and out[0].company_name == "Acme Kitchens Ltd"
    assert out[0].emails == ["sam@acme.example"] and out[0].business_phones == ["020 7946 0000"]
    assert out[1].company_name == "" and out[1].emails == []


async def test_list_contacts_forbidden_without_consent():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})

    with pytest.raises(GraphError) as err:
        await _provider(handler).list_contacts()
    assert err.value.status == 403
