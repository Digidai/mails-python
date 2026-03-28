"""mails-agent — Python SDK for email capabilities for AI agents."""

from .client import AsyncMailsClient, MailsClient
from .exceptions import ApiError, AuthError, MailsError, NotFoundError
from .models import Attachment, Email, MeInfo, SendResult, VerificationCode

__version__ = "1.4.0b2"
__all__ = [
    "MailsClient",
    "AsyncMailsClient",
    "Email",
    "Attachment",
    "SendResult",
    "VerificationCode",
    "MeInfo",
    "MailsError",
    "AuthError",
    "NotFoundError",
    "ApiError",
]
