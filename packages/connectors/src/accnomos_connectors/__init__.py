"""Provider-neutral connectors (PRD §4.2, decision H21).

Everything above this package talks to these interfaces. Microsoft Graph is the first
implementation; Google Drive/Gmail/Calendar next. Providers never leak into ledger/VAT code.
"""

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarProvider,
    ContactsProvider,
    FileRef,
    MailAttachment,
    MailMessage,
    MailProvider,
    ConflictError,
    StorageProvider,
)
from accnomos_connectors.fake import FakeContactsProvider, FakeMailProvider, FakeStorageProvider
from accnomos_connectors.msgraph import GraphContactsProvider, GraphError, GraphMailProvider, GraphStorageProvider

__all__ = [
    "AddressBookContact",
    "CalendarProvider",
    "ContactsProvider",
    "FileRef",
    "MailAttachment",
    "MailMessage",
    "MailProvider",
    "StorageProvider",
    "ConflictError",
    "FakeContactsProvider",
    "FakeMailProvider",
    "FakeStorageProvider",
    "GraphContactsProvider",
    "GraphError",
    "GraphMailProvider",
    "GraphStorageProvider",
]
