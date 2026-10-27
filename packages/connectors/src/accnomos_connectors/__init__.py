"""Provider-neutral connectors (PRD §4.2, decision H21).

Everything above this package talks to these interfaces. Microsoft Graph is the first
implementation; Google Drive/Gmail/Calendar next. Providers never leak into ledger/VAT code.
"""

from accnomos_connectors.base import (
    CalendarProvider,
    FileRef,
    MailAttachment,
    MailMessage,
    MailProvider,
    MailSender,
    ConflictError,
    OutgoingAttachment,
    OutgoingMail,
    StorageProvider,
)
from accnomos_connectors.fake import FakeMailProvider, FakeMailSender, FakeStorageProvider
from accnomos_connectors.msgraph import GraphError, GraphMailProvider, GraphMailSender, GraphStorageProvider

__all__ = [
    "CalendarProvider",
    "FileRef",
    "MailAttachment",
    "MailMessage",
    "MailProvider",
    "MailSender",
    "OutgoingAttachment",
    "OutgoingMail",
    "StorageProvider",
    "ConflictError",
    "FakeMailProvider",
    "FakeMailSender",
    "FakeStorageProvider",
    "GraphError",
    "GraphMailProvider",
    "GraphMailSender",
    "GraphStorageProvider",
]
