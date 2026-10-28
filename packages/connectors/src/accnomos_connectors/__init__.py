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
    Identity,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailProvider,
    MailSender,
    OutgoingAttachment,
    OutgoingMail,
    SharedFolder,
    SharedRoot,
    SharePermission,
    SharingProvider,
    StorageProvider,
)
from accnomos_connectors.fake import (
    FakeCalendarProvider,
    FakeContactsProvider,
    FakeMailProvider,
    FakeMailSender,
    FakeSharingProvider,
    FakeStorageProvider,
)
from accnomos_connectors.msgraph import (
    GraphCalendarProvider,
    GraphContactsProvider,
    GraphError,
    GraphMailProvider,
    GraphMailSender,
    GraphSharingProvider,
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
    "SharedFolder",
    "SharedRoot",
    "SharePermission",
    "SharingProvider",
    "Identity",
    "ConflictError",
    "FakeCalendarProvider",
    "FakeContactsProvider",
    "FakeMailProvider",
    "FakeMailSender",
    "FakeSharingProvider",
    "FakeStorageProvider",
    "GraphCalendarProvider",
    "GraphContactsProvider",
    "GraphError",
    "GraphMailProvider",
    "GraphMailSender",
    "GraphSharingProvider",
    "GraphStorageProvider",
]
