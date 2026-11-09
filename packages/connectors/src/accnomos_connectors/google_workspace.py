"""Google Workspace: Gmail MailProvider and MailSender, Google Calendar CalendarProvider and People ContactsProvider.

The token is a Google OAuth access token with these scopes (nothing broader):

* `gmail.readonly`    -> messages.list / messages.get / attachments.get
* `gmail.compose`     -> drafts.create (reply drafts) and messages.send (GoogleMailSender only)
* `calendar.events`   -> Calendar v3 events on the user's primary calendar
* `contacts.readonly` -> People API `people/me/connections`

Semantics mirror `msgraph.py`: nothing is moved, labelled, marked read or deleted; `create_reply_draft` only saves a
draft; sending happens only through `GoogleMailSender.send` (messages.send, the same single action Graph's sender
performs, and `gmail.compose` covers it). Errors are mapped as in `_GraphHttp`: 404/410 -> FileNotFoundError,
412 -> ConflictError, 409 -> FileExistsError, other 4xx/5xx -> GoogleError; 429/503 (and Google's 403 rate-limit
reasons) are retried honouring Retry-After. The token only ever goes to the three Google API origins below.

`TRANSPORT` is the module-level test hook the runtime's other connectors use (`truelayer.TRANSPORT`,
`payment_providers.TRANSPORT`): when set, every provider built without its own `client` talks through it.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, parseaddr
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarEvent,
    CalendarProvider,
    ConflictError,
    ContactsProvider,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailProvider,
    MailSender,
    NewCalendarEvent,
    OutgoingMail,
)

GMAIL_ORIGIN = "https://gmail.googleapis.com"
GMAIL = f"{GMAIL_ORIGIN}/gmail/v1/users/me"
CALENDAR_ORIGIN = "https://www.googleapis.com"
CALENDAR = f"{CALENDAR_ORIGIN}/calendar/v3/calendars/primary"
PEOPLE_ORIGIN = "https://people.googleapis.com"
PEOPLE = f"{PEOPLE_ORIGIN}/v1"
_ORIGINS = tuple(f"{o}/" for o in (GMAIL_ORIGIN, CALENDAR_ORIGIN, PEOPLE_ORIGIN))

MAX_RETRIES = 3
MAX_RETRY_AFTER_S = 30.0
TIMEOUT = 60.0
#: Test hook (see module docstring). None means the real network.
TRANSPORT: httpx.AsyncBaseTransport | None = None
#: Key of the private extended property that tags Accnomos's own calendar events.
ACCNOMOS_KEY_PROP = "accnomosKey"


class GoogleError(RuntimeError):
    """A Google API call failed with a status we do not map to a builtin exception."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Google {status}: {message}")
        self.status = status


_RATE_REASONS = ("ratelimitexceeded", "userratelimitexceeded")


class _GoogleHttp:
    """Bearer token, retries on 429/503 and error mapping shared by the Google providers."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT)
        self._owns_client = client is None
        self._auth = {"Authorization": f"Bearer {token}"}
        self._sleep = sleep

    def set_token(self, token: str) -> None:
        """Use a fresh token from the next request on (Google access tokens last an hour)."""
        if not token.strip():
            raise ValueError("empty token")
        self._auth = {"Authorization": f"Bearer {token.strip()}"}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, method: str, url: str, *, ok404: bool = False, **kw: Any) -> httpx.Response:
        if not url.startswith(_ORIGINS):
            raise ValueError("refusing to send the Google token outside the Google API origins")
        headers = {**self._auth, **kw.pop("headers", {})}
        for attempt in range(MAX_RETRIES + 1):
            resp = await self._client.request(method, url, headers=headers, **kw)
            retryable = resp.status_code in (429, 503) or (
                resp.status_code == 403 and any(r in resp.text.lower() for r in _RATE_REASONS)
            )
            if not retryable or attempt == MAX_RETRIES:
                break
            await self._sleep(self._retry_after(resp))
        if resp.status_code in (404, 410):
            if ok404:
                return resp
            raise FileNotFoundError(url)
        if resp.status_code == 412:
            raise ConflictError(url)
        if resp.status_code == 409:
            raise FileExistsError(url)
        if resp.status_code >= 400:
            raise GoogleError(resp.status_code, resp.text[:300])
        return resp

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        try:
            return min(MAX_RETRY_AFTER_S, max(0.0, float(resp.headers.get("Retry-After", "1"))))
        except ValueError:
            return 1.0


# ---------------------------------------------------------------------- #
# Gmail helpers
# ---------------------------------------------------------------------- #

_TAG_BREAKS = re.compile(r"(?i)<\s*(?:br|/p|/div|/tr|/li|/h[1-6])\b[^>]*>")
_DROP_BLOCKS = re.compile(r"(?is)<(script|style|head)\b.*?</\1\s*>")
_TAGS = re.compile(r"<[^>]+>")


def _html_to_text(raw: str) -> str:
    text = _TAGS.sub("", _TAG_BREAKS.sub("\n", _DROP_BLOCKS.sub("", raw)))
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    """Header name (lower-cased) -> value; the first occurrence wins."""
    out: dict[str, str] = {}
    for h in payload.get("headers") or []:
        out.setdefault(str(h.get("name", "")).lower(), h.get("value") or "")
    return out


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # malformed encoded-word: show it raw rather than fail the listing
        return value


def _walk(payload: dict[str, Any]):
    yield payload
    for part in payload.get("parts") or []:
        yield from _walk(part)


def _is_attachment(part: dict[str, Any]) -> bool:
    return bool(part.get("filename")) and bool(
        (part.get("body") or {}).get("attachmentId") or (part.get("body") or {}).get("data")
    )


def _part_text(part: dict[str, Any]) -> str:
    charset = "utf-8"
    ctype = _headers(part).get("content-type", "")
    m = re.search(r'charset="?([\w.-]+)"?', ctype, re.IGNORECASE)
    if m:
        charset = m.group(1)
    raw = _b64url_decode((part.get("body") or {}).get("data") or "")
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _received(m: dict[str, Any]) -> datetime:
    ms = m.get("internalDate")
    return datetime.fromtimestamp(int(ms) / 1000, UTC) if ms else datetime(1970, 1, 1, tzinfo=UTC)


def _quote_text(text: str, limit: int = 8000) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n[...]"
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def _one_line(value: str) -> str:
    return " ".join(value.split())


class GoogleMailProvider(_GoogleHttp, MailProvider):
    """Gmail via the REST API v1 (`gmail.readonly`; `create_reply_draft` needs `gmail.compose`). Only GET requests
    are sent apart from drafts.create, which saves a draft and never sends.

    Gmail has labels, not folders: `folder` None/"all" is every mailbox message except Spam and Trash (Gmail's own
    default), "inbox" is the INBOX label, "archive" is "not in Inbox, Sent, Drafts, Spam or Trash", anything else is
    a user label found by name (FileNotFoundError when there is none)."""

    PAGE = 100
    META_HEADERS = ("From", "Subject")
    CONCURRENCY = 5

    def __init__(self, token: str, **kw: Any) -> None:
        super().__init__(token, **kw)
        self._label_ids: dict[str, str] = {}

    # ------------------------------------------------------------------ #

    @staticmethod
    def _link(message_id: str) -> str:
        return f"https://mail.google.com/mail/u/0/#all/{message_id}"

    async def _label_id(self, name: str) -> str:
        if name not in self._label_ids:
            labels = (await self._request("GET", f"{GMAIL}/labels")).json().get("labels") or []
            for lab in labels:
                if lab.get("type") == "user" and (lab.get("name") or "").lower() == name.lower():
                    self._label_ids[name] = lab["id"]
                    break
            else:
                raise FileNotFoundError(f"mail label {name!r}")
        return self._label_ids[name]

    async def _scope(self, folder: str | None, default: str | None) -> tuple[list[str], list[str]]:
        """(label ids that must all be on the message, extra q terms) for a `folder` argument."""
        want = default if folder in (None, "", "all") else folder
        if want is None:
            return [], []
        if want.lower() == "inbox":
            return ["INBOX"], []
        if want.lower() == "archive":
            return [], ["-in:inbox", "-in:sent", "-in:drafts", "-in:spam", "-in:trash"]
        return [await self._label_id(want)], []

    async def _list(
        self, since: datetime, max_results: int, label_ids: list[str], terms: list[str]
    ) -> list[dict[str, Any]]:
        """messages.list (ids), then messages.get metadata for each; newest first (Gmail's own order)."""
        q = " ".join([f"after:{int(since.timestamp())}", *terms])
        params: dict[str, Any] = {"q": q, "maxResults": min(self.PAGE, max(1, max_results))}
        if label_ids:
            params["labelIds"] = label_ids
        ids: list[str] = []
        while len(ids) < max_results:
            page = (await self._request("GET", f"{GMAIL}/messages", params=params)).json()
            ids.extend(m["id"] for m in page.get("messages") or [])
            if not page.get("nextPageToken"):
                break
            params = {**params, "pageToken": page["nextPageToken"]}
        sem = asyncio.Semaphore(self.CONCURRENCY)

        async def fetch(mid: str) -> dict[str, Any] | None:
            async with sem:
                r = await self._request(
                    "GET",
                    f"{GMAIL}/messages/{quote(mid, safe='')}",
                    ok404=True,  # deleted between the list and the get
                    params={"format": "metadata", "metadataHeaders": list(self.META_HEADERS)},
                )
            return None if r.status_code == 404 else r.json()

        got = await asyncio.gather(*(fetch(i) for i in ids[:max_results]))
        return [m for m in got if m]

    def _to_message(self, m: dict[str, Any], *, has_attachments: bool, triage: bool) -> MailMessage:
        h = _headers(m.get("payload") or {})
        name, address = parseaddr(_decode_header(h.get("from", "")))
        return MailMessage(
            id=m["id"],
            received_at=_received(m),
            from_address=address.lower(),
            from_name=name,
            subject=_one_line(_decode_header(h.get("subject", ""))),
            has_attachments=has_attachments,
            web_link=self._link(m["id"]),
            conversation_id=(m.get("threadId") or m["id"]) if triage else "",
            body_preview=(html.unescape(m.get("snippet") or ""))[:255] if triage else "",
            is_read="UNREAD" not in (m.get("labelIds") or []),
        )

    # ------------------------------------------------------------------ #

    async def list_messages(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        labels, terms = await self._scope(folder, None)
        msgs = await self._list(since, max_results, labels, ["has:attachment", *terms])
        return [self._to_message(m, has_attachments=True, triage=False) for m in msgs]

    async def list_without_attachments(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        labels, terms = await self._scope(folder, "inbox")
        msgs = await self._list(since, max_results, labels, ["-has:attachment", *terms])
        out = [self._to_message(m, has_attachments=False, triage=False) for m in msgs]
        for msg, raw in zip(out, msgs, strict=True):
            msg.body_preview = html.unescape(raw.get("snippet") or "")[:255]
        return out

    async def list_recent(self, since: datetime, max_results: int = 100) -> list[MailMessage]:
        msgs = await self._list(since, max_results, ["INBOX"], [])
        # has_attachments is not known from metadata, and triage does not need it
        return [self._to_message(m, has_attachments=False, triage=True) for m in msgs]

    async def _full(self, message_id: str) -> dict[str, Any]:
        r = await self._request("GET", f"{GMAIL}/messages/{quote(message_id, safe='')}", params={"format": "full"})
        return r.json()

    @staticmethod
    def _text_of(message: dict[str, Any]) -> str:
        parts = list(_walk(message.get("payload") or {}))
        for want in ("text/plain", "text/html"):
            for p in parts:
                if p.get("mimeType") == want and not p.get("filename") and (p.get("body") or {}).get("data"):
                    text = _part_text(p)
                    return text if want == "text/plain" else _html_to_text(text)
        return ""

    async def message_text(self, message_id: str) -> str:
        return self._text_of(await self._full(message_id))

    async def list_attachments(self, message_id: str) -> list[MailAttachment]:
        out: list[MailAttachment] = []
        for p in _walk((await self._full(message_id)).get("payload") or {}):
            if not _is_attachment(p):
                continue
            h = _headers(p)
            body = p.get("body") or {}
            out.append(
                MailAttachment(
                    id=body.get("attachmentId") or f"part:{p.get('partId', '')}",
                    name=p["filename"],
                    content_type=(p.get("mimeType") or "").lower(),
                    size=int(body.get("size") or 0),
                    is_inline=h.get("content-disposition", "").lower().startswith("inline") or "content-id" in h,
                )
            )
        return out

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        if attachment_id.startswith("part:"):  # small attachment Gmail inlined in the message body
            part_id = attachment_id[5:]
            for p in _walk((await self._full(message_id)).get("payload") or {}):
                if str(p.get("partId", "")) == part_id and (p.get("body") or {}).get("data"):
                    return _b64url_decode(p["body"]["data"])
            raise FileNotFoundError(attachment_id)
        url = f"{GMAIL}/messages/{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}"
        return _b64url_decode((await self._request("GET", url)).json().get("data") or "")

    async def create_reply_draft(self, message_id: str, body_text: str) -> MailDraft:
        """drafts.create with the reply's MIME (`In-Reply-To`, `References`, `threadId`), `body_text` above the
        quoted original. Never sends."""
        orig = await self._full(message_id)
        h = _headers(orig.get("payload") or {})
        to = h.get("reply-to") or h.get("from") or ""
        subject = _one_line(_decode_header(h.get("subject", "")))
        msg_id = h.get("message-id", "").strip()
        refs = " ".join(x for x in (h.get("references", "").strip(), msg_id) if x)
        sender = _decode_header(h.get("from", "")) or "the sender"
        when = _received(orig).strftime("%a, %d %b %Y at %H:%M UTC")
        quoted = _quote_text(self._text_of(orig))
        mail = EmailMessage(policy=policy.SMTP)
        mail["To"] = _one_line(to)
        mail["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()
        if msg_id:
            mail["In-Reply-To"] = msg_id
        if refs:
            mail["References"] = refs
        mail["Date"] = formatdate(localtime=False)
        mail.set_content(f"{body_text}\n\nOn {when}, {sender} wrote:\n{quoted}\n" if quoted else f"{body_text}\n")
        payload = {
            "message": {"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode(), "threadId": orig.get("threadId")}
        }
        draft = (await self._request("POST", f"{GMAIL}/drafts", json=payload)).json()
        mid = (draft.get("message") or {}).get("id") or draft["id"]
        return MailDraft(id=draft["id"], web_link=f"https://mail.google.com/mail/u/0/#drafts?compose={mid}")


class GoogleContactsProvider(_GoogleHttp, ContactsProvider):
    """Google contacts via the People API (`contacts.readonly`). Read-only: only GET requests are ever sent.
    `business_phones` are the numbers typed "work" or "workMobile"."""

    PAGE = 1000  # the API maximum
    FIELDS = "names,emailAddresses,phoneNumbers,organizations"
    WORK_PHONE_TYPES = frozenset({"work", "workmobile"})

    async def list_contacts(self, max_results: int = 1000) -> list[AddressBookContact]:
        params: dict[str, Any] = {
            "personFields": self.FIELDS,
            "pageSize": min(self.PAGE, max(1, max_results)),
            "sortOrder": "LAST_MODIFIED_DESCENDING",
        }
        out: list[AddressBookContact] = []
        while len(out) < max_results:
            page = (await self._request("GET", f"{PEOPLE}/people/me/connections", params=params)).json()
            for c in page.get("connections") or []:
                names, orgs = c.get("names") or [], c.get("organizations") or []
                emails = [(e.get("value") or "").strip() for e in c.get("emailAddresses") or []]
                phones = [
                    (p.get("value") or "").strip()
                    for p in c.get("phoneNumbers") or []
                    if (p.get("type") or "").lower() in self.WORK_PHONE_TYPES
                ]
                out.append(
                    AddressBookContact(
                        id=c["resourceName"],
                        display_name=((names[0].get("displayName") if names else "") or "").strip(),
                        company_name=((orgs[0].get("name") if orgs else "") or "").strip(),
                        emails=[e for e in emails if e],
                        business_phones=[p for p in phones if p],
                    )
                )
            if not page.get("nextPageToken"):
                break
            params = {**params, "pageToken": page["nextPageToken"]}
        return out[:max_results]


class GoogleMailSender(_GoogleHttp, MailSender):
    """`messages.send` (allowed by `gmail.compose`), saved in the user's Sent mail. Sends, exactly as Graph's
    sender does, and only when the caller has the user's confirmation. The message goes in one JSON request as
    base64url MIME; it is refused before anything is sent when that request would exceed `MAX_REQUEST_BYTES`
    (Gmail's resumable media upload, which allows 35 MB, is not used)."""

    MAX_REQUEST_BYTES = 4_000_000

    async def send(self, mail: OutgoingMail) -> None:
        msg = EmailMessage(policy=policy.SMTP)
        msg["To"] = _one_line(mail.to)
        msg["Subject"] = _one_line(mail.subject)
        msg["Date"] = formatdate(localtime=False)
        msg.set_content(mail.body_text)
        for a in mail.attachments:
            maintype, _, subtype = (a.content_type or "application/octet-stream").partition("/")
            msg.add_attachment(
                a.data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=a.name
            )
        content = json.dumps({"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}, separators=(",", ":")).encode()
        if len(content) > self.MAX_REQUEST_BYTES:
            raw = sum(len(a.data) for a in mail.attachments)
            raise ValueError(
                f"The email is too big to send in one go ({raw / 1_000_000:.1f} MB of attachments; "
                f"about {self.MAX_REQUEST_BYTES * 3 // 4 / 1_000_000:.1f} MB is the most Gmail accepts here)"
            )
        await self._request(
            "POST", f"{GMAIL}/messages/send", content=content, headers={"Content-Type": "application/json"}
        )


# ---------------------------------------------------------------------- #
# Calendar
# ---------------------------------------------------------------------- #

_LONDON = ZoneInfo("Europe/London")


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_time(value: dict[str, Any] | None) -> datetime:
    """A Calendar start/end -> aware UTC. An all-day `date` is midnight in the event's zone (default London)."""
    value = value or {}
    if value.get("dateTime"):
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(UTC)
    if value.get("date"):
        try:
            zone = ZoneInfo(value.get("timeZone") or "Europe/London")
        except Exception:
            zone = _LONDON
        return datetime.combine(date.fromisoformat(value["date"]), time(0), zone).astimezone(UTC)
    return datetime(1970, 1, 1, tzinfo=UTC)


class GoogleCalendarProvider(_GoogleHttp, CalendarProvider):
    """Google Calendar v3, the user's primary calendar (`calendar.events`). Writes happen only after the user has
    approved them; `update_event` and `move_event` PATCH, so attendees and anything Accnomos does not own stay."""

    PAGE = 250

    @staticmethod
    def _event(e: dict[str, Any], key: str | None = None) -> CalendarEvent:
        private = (e.get("extendedProperties") or {}).get("private") or {}
        if private.get(ACCNOMOS_KEY_PROP) is not None:
            key = private[ACCNOMOS_KEY_PROP]
        if e.get("transparency") == "transparent":
            show_as = "free"
        else:
            show_as = "tentative" if e.get("status") == "tentative" else "busy"
        return CalendarEvent(
            id=e["id"],
            subject=e.get("summary") or "",
            start=_event_time(e.get("start")),
            end=_event_time(e.get("end")),
            location=e.get("location") or "",
            body_preview=(e.get("description") or "")[:255],
            is_all_day="date" in (e.get("start") or {}),
            show_as=show_as,
            web_link=e.get("htmlLink") or "",
            key=key,
        )

    @staticmethod
    def _timed(dt: datetime) -> dict[str, Any]:
        if dt.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        return {"dateTime": _utc_z(dt), "timeZone": "UTC", "date": None}

    @classmethod
    def _payload(cls, event: NewCalendarEvent, *, patch: bool = False) -> dict[str, Any]:
        """The event body. For a PATCH the other time form is nulled, so all-day <-> timed switches cleanly."""
        if event.start.tzinfo is None or event.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if event.is_all_day:  # end is exclusive in Calendar as well
            start = {"date": event.start.astimezone(_LONDON).date().isoformat(), "dateTime": None}
            end = {"date": event.end.astimezone(_LONDON).date().isoformat(), "dateTime": None}
        else:
            start, end = cls._timed(event.start), cls._timed(event.end)
        payload: dict[str, Any] = {
            "summary": event.subject,
            "start": start,
            "end": end,
            "location": event.location,
            "description": event.body,
            "transparency": "transparent" if event.is_all_day else "opaque",
            "reminders": (
                {"useDefault": False, "overrides": [{"method": "popup", "minutes": event.reminder_minutes}]}
                if event.reminder_minutes is not None
                else {"useDefault": False}
            ),
        }
        if event.key is not None:
            payload["extendedProperties"] = {"private": {ACCNOMOS_KEY_PROP: event.key}}
        if not patch:
            for edge in (payload["start"], payload["end"]):
                edge.pop("date", None) if edge.get("date") is None else edge.pop("dateTime", None)
        return payload

    @staticmethod
    def _url(event_id: str = "") -> str:
        return f"{CALENDAR}/events" + (f"/{quote(event_id, safe='')}" if event_id else "")

    async def list_range(self, start: date, end: date, tz: str = "Europe/London") -> list[CalendarEvent]:
        zone = ZoneInfo(tz)
        lo = datetime.combine(start, time(0), zone)
        hi = datetime.combine(end + timedelta(days=1), time(0), zone)
        params: dict[str, Any] = {
            "timeMin": _utc_z(lo),
            "timeMax": _utc_z(hi),
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "false",
            "maxResults": self.PAGE,
        }
        out: list[CalendarEvent] = []
        token: str | None = None
        while True:
            page = (
                await self._request("GET", self._url(), params={**params, **({"pageToken": token} if token else {})})
            ).json()
            out.extend(self._event(e) for e in page.get("items") or [] if e.get("status") != "cancelled")
            token = page.get("nextPageToken")
            if not token:
                break
        return sorted(out, key=lambda e: e.start)

    async def list_events(self, day: date, tz: str = "Europe/London") -> list[CalendarEvent]:
        return await self.list_range(day, day, tz)

    async def create_event(self, subject: str, start: datetime, end: datetime, location: str, body: str) -> str:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        payload: dict[str, Any] = {
            "summary": subject,
            "start": {"dateTime": _utc_z(start), "timeZone": "UTC"},
            "end": {"dateTime": _utc_z(end), "timeZone": "UTC"},
            "description": body,
            "transparency": "opaque",
            "reminders": {"useDefault": False},
        }
        if location:
            payload["location"] = location
        return (await self._request("POST", self._url(), json=payload)).json()["id"]

    async def add_event(self, event: NewCalendarEvent) -> CalendarEvent:
        made = (await self._request("POST", self._url(), json=self._payload(event))).json()
        return self._event(made, event.key)

    async def update_event(self, event_id: str, event: NewCalendarEvent) -> CalendarEvent:
        changed = (await self._request("PATCH", self._url(event_id), json=self._payload(event, patch=True))).json()
        return self._event(changed, event.key)

    async def move_event(self, event_id: str, start: datetime, end: datetime) -> CalendarEvent:
        body = {"start": self._timed(start), "end": self._timed(end)}
        changed = (await self._request("PATCH", self._url(event_id), json=body)).json()
        return self._event(changed, None)

    async def delete_event(self, event_id: str) -> None:
        await self._request("DELETE", self._url(event_id))  # 404 and 410 (already deleted): FileNotFoundError
