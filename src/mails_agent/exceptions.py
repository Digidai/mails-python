"""Custom exceptions for the mails-agent SDK."""


class MailsError(Exception):
    """Base exception for mails-agent SDK."""

    pass


class AuthError(MailsError):
    """Authentication failed (HTTP 401/403)."""

    pass


class NotFoundError(MailsError):
    """Resource not found (HTTP 404)."""

    pass


class ApiError(MailsError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
