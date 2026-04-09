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


@dataclass
class VerificationCode:
    """A verification code extracted from an email."""

    code: str
    from_address: str = ""
    subject: str = ""
    id: Optional[str] = None
    received_at: Optional[str] = None


@dataclass
class MailboxStats:
    """Result of the /api/stats endpoint."""

    mailbox: str
    total_emails: int = 0
    inbound: int = 0
    outbound: int = 0
    emails_this_month: int = 0


@dataclass
class MeInfo:
    """Result of the /api/me endpoint."""

    worker: str
    mailbox: Optional[str] = None
    send: bool = False
