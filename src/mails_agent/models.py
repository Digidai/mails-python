"""Data models for the mails-agent SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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


@dataclass
class SendResult:
    """Result of a send operation."""

    id: str
    provider: str
    provider_id: Optional[str] = None


@dataclass
class VerificationCode:
    """A verification code extracted from an email."""

    code: str
    from_address: str
    subject: str
