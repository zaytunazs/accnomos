"""Provider-neutral connectors (PRD §4.2, decision H21).

Everything above this package talks to these interfaces. Microsoft Graph is the first
implementation; Google Drive/Gmail/Calendar next. Providers never leak into ledger/VAT code.
"""

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarEvent,
    CalendarProvider,
    ConflictError,
    ContactsProvider,
    FileRef,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailProvider,
    MailSender,
    OutgoingAttachment,
    OutgoingMail,
    StorageProvider,
)
from accnomos_connectors.fake import (
    FakeCalendarProvider,
    FakeContactsProvider,
    FakeMailProvider,
    FakeMailSender,
    FakeStorageProvider,
)
from accnomos_connectors.msgraph import (
    GraphCalendarProvider,
    GraphContactsProvider,
    GraphError,
    GraphMailProvider,
    GraphMailSender,
    GraphStorageProvider,
)

__all__ = [
    "AddressBookContact",
    "CalendarEvent",
    "CalendarProvider",
    "ContactsProvider",
    "FileRef",
    "MailAttachment",
    "MailDraft",
    "MailMessage",
    "MailProvider",
    "MailSender",
    "OutgoingAttachment",
    "OutgoingMail",
    "StorageProvider",
    "ConflictError",
    "FakeCalendarProvider",
    "FakeContactsProvider",
    "FakeMailProvider",
    "FakeMailSender",
    "FakeStorageProvider",
    "GraphCalendarProvider",
    "GraphContactsProvider",
    "GraphError",
    "GraphMailProvider",
    "GraphMailSender",
    "GraphStorageProvider",
]
