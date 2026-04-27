"""mails-agent — Python SDK for email capabilities for AI agents."""

from .client import AsyncMailsClient, MailsClient
from .exceptions import ApiError, AuthError, MailsError, NotFoundError
from .models import (
    Attachment,
    ClaimResult,
    DnsRecord,
    DnsRecords,
    Domain,
    DomainVerification,
    Email,
    EmailThread,
    IngestStats,
    Mailbox,
    MailboxDeleteResult,
    MailboxStats,
    MeInfo,
    SendResult,
    VerificationCode,
    WebhookRoute,
    WebhookRouteList,
)

__version__ = "1.7.1"
__all__ = [
    "MailsClient",
    "AsyncMailsClient",
    # Core models
    "Email",
    "EmailThread",
    "Attachment",
    "SendResult",
    "VerificationCode",
    "MailboxStats",
    "IngestStats",
    "MeInfo",
    # Domain management
    "Domain",
    "DomainVerification",
    "DnsRecord",
    "DnsRecords",
    # Mailbox management
    "Mailbox",
    "MailboxDeleteResult",
    # Webhook routes
    "WebhookRoute",
    "WebhookRouteList",
    # Claim
    "ClaimResult",
    # Exceptions
    "MailsError",
    "AuthError",
    "NotFoundError",
    "ApiError",
]
