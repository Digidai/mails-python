"""mails-agent — Python SDK for email capabilities for AI agents."""

from .client import AsyncMailsClient, MailsClient
from .exceptions import ApiError, AuthError, MailsError, NotFoundError
from .models import Attachment, Email, EmailThread, MeInfo, SendResult, VerificationCode

__version__ = "1.5.1"
__all__ = [
    "MailsClient",
    "AsyncMailsClient",
    "Email",
    "EmailThread",
    "Attachment",
    "SendResult",
    "VerificationCode",
    "MeInfo",
    "MailsError",
    "AuthError",
    "NotFoundError",
    "ApiError",
]
