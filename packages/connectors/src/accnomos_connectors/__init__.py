"""Provider-neutral connectors (PRD §4.2, decision H21).

Everything above this package talks to these three interfaces. Microsoft Graph is the first
implementation; Google Drive/Gmail/Calendar next. Providers never leak into ledger/VAT code.
"""

from accnomos_connectors.base import (
    CalendarProvider,
    FileRef,
    MailAttachment,
    MailMessage,
    MailProvider,
    ConflictError,
    StorageProvider,
)
from accnomos_connectors.fake import FakeMailProvider, FakeStorageProvider
from accnomos_connectors.msgraph import GraphError, GraphMailProvider, GraphStorageProvider

__all__ = [
    "CalendarProvider",
    "FileRef",
    "MailAttachment",
    "MailMessage",
    "MailProvider",
    "StorageProvider",
    "ConflictError",
    "FakeMailProvider",
    "FakeStorageProvider",
    "GraphError",
    "GraphMailProvider",
    "GraphStorageProvider",
]
