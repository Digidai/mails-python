"""Data models for the mails-agent SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Attachment:
    """Represents an email attachment."""

    id: str
    email_id: str
    filename: str
    content_type: str
    size_bytes: Optional[int] = None
    content_disposition: Optional[str] = None
    content_id: Optional[str] = None
    mime_part_index: int = 0
    text_content: str = ""
    text_extraction_status: str = "pending"
    storage_key: Optional[str] = None
    downloadable: bool = False
    created_at: str = ""


@dataclass
class Email:
    """Represents an email message."""

    id: str
    mailbox: str
    from_address: str
    from_name: str
    subject: str
    direction: str  # 'inbound' | 'outbound'
    status: str
    received_at: str
    has_attachments: bool = False
    attachment_count: int = 0
    body_text: str = ""
    body_html: str = ""
    code: Optional[str] = None
    to_address: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: Optional[str] = None
    attachment_names: str = ""
    attachment_search_text: str = ""
    raw_storage_key: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    created_at: str = ""
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    labels: List[str] = field(default_factory=list)


@dataclass
class EmailThread:
    """Represents a conversation thread."""

    thread_id: str
    latest_email_id: str
    subject: str
    from_address: str
    from_name: str
    received_at: str
    message_count: int
    has_attachments: bool = False
    code: Optional[str] = None


@dataclass
class SendResult:
    """Result of a send operation."""

    id: str
    provider: str = ""
    provider_id: Optional[str] = None
    thread_id: Optional[str] = None


@dataclass
class VerificationCode:
    """A verification code extracted from an email."""

    code: str
    from_address: str = ""
    subject: str = ""
    id: Optional[str] = None
    received_at: Optional[str] = None


@dataclass
class IngestStats:
    """Ingest pipeline statistics."""

    pending: int = 0
    parsed: int = 0
    failed: int = 0


@dataclass
class MailboxStats:
    """Result of the /api/stats endpoint."""

    mailbox: str
    total_emails: int = 0
    inbound: int = 0
    outbound: int = 0
    emails_this_month: int = 0
    ingest: Optional[IngestStats] = None
    suppression_count: int = 0
    webhook_routes: int = 0


@dataclass
class MeInfo:
    """Result of the /api/me endpoint."""

    worker: str
    mailbox: Optional[str] = None
    send: bool = False


# ------------------------------------------------------------------
# Domain management
# ------------------------------------------------------------------


@dataclass
class DnsRecord:
    """A single DNS record required for domain verification."""

    type: str
    host: str
    value: str
    purpose: str
    priority: Optional[int] = None


@dataclass
class DnsRecords:
    """DNS records required for a custom domain."""

    mx: Optional[DnsRecord] = None
    spf: Optional[DnsRecord] = None
    dmarc: Optional[DnsRecord] = None


@dataclass
class Domain:
    """A custom email domain."""

    id: str
    domain: str
    status: str
    mx_verified: bool = False
    spf_verified: bool = False
    dkim_verified: bool = False
    created_at: str = ""
    verified_at: Optional[str] = None
    dns_records: Optional[DnsRecords] = None
    instructions: Optional[str] = None


@dataclass
class DomainVerification:
    """Result of a domain verification check."""

    id: str
    domain: str
    status: str
    mx_verified: bool = False
    spf_verified: bool = False
    message: str = ""


# ------------------------------------------------------------------
# Mailbox management
# ------------------------------------------------------------------


@dataclass
class Mailbox:
    """Mailbox info and status."""

    mailbox: str
    status: str = ""
    webhook_url: Optional[str] = None
    created_at: str = ""


@dataclass
class MailboxDeleteResult:
    """Result of deleting a mailbox."""

    ok: bool
    deleted: str = ""
    r2_blobs_deleted: int = 0


# ------------------------------------------------------------------
# Webhook routes
# ------------------------------------------------------------------


@dataclass
class WebhookRoute:
    """A label-specific webhook route."""

    label: str
    webhook_url: str
    created_at: str = ""


@dataclass
class WebhookRouteList:
    """Response from listing webhook routes."""

    mailbox: str
    routes: List["WebhookRoute"] = field(default_factory=list)


# ------------------------------------------------------------------
# Claim
# ------------------------------------------------------------------


@dataclass
class ClaimResult:
    """Result of claiming a new mailbox."""

    mailbox: str
    api_key: str
