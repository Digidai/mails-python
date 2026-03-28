"""mails-agent — Python SDK for email capabilities for AI agents."""

from .client import AsyncMailsClient, MailsClient
from .exceptions import ApiError, AuthError, MailsError, NotFoundError
from .models import Email, SendResult, VerificationCode

__version__ = "1.4.0b1"
__all__ = [
    "MailsClient",
    "AsyncMailsClient",
    "Email",
    "SendResult",
    "VerificationCode",
    "MailsError",
    "AuthError",
    "NotFoundError",
    "ApiError",
]
