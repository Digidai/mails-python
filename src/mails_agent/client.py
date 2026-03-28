"""Synchronous and asynchronous HTTP clients for the mails-agent API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

import httpx

from .exceptions import ApiError, AuthError, NotFoundError
from .models import Email, SendResult, VerificationCode


def _parse_email(data: Dict[str, Any]) -> Email:
    """Convert a raw API dict into an Email dataclass."""
    return Email(
        id=data["id"],
        mailbox=data.get("mailbox", ""),
        from_address=data.get("from_address", ""),
        from_name=data.get("from_name", ""),
        subject=data.get("subject", ""),
        direction=data.get("direction", "inbound"),
        status=data.get("status", ""),
        received_at=data.get("received_at", ""),
        has_attachments=bool(data.get("has_attachments", False)),
        attachment_count=int(data.get("attachment_count", 0)),
        body_text=data.get("body_text", ""),
        body_html=data.get("body_html", ""),
        code=data.get("code"),
    )


def _handle_error(response: httpx.Response) -> None:
    """Raise the appropriate exception for non-2xx responses."""
    if response.status_code == 401 or response.status_code == 403:
        raise AuthError(f"Authentication failed ({response.status_code})")
    if response.status_code == 404:
        raise NotFoundError("Resource not found")
    if not response.is_success:
        try:
            body = response.json()
            message = body.get("error", response.reason_phrase)
        except Exception:
            message = response.reason_phrase or f"HTTP {response.status_code}"
        raise ApiError(message, response.status_code)


class MailsClient:
    """Synchronous client for the mails-agent API.

    Args:
        api_url: Worker API base URL (e.g. ``https://mails-worker.genedai.workers.dev``).
        token: API key or worker token for authentication.
        mailbox: Your email address (e.g. ``agent@mails0.com``).
        timeout: Request timeout in seconds. Defaults to 60 to accommodate
            long-polling ``wait_for_code`` calls.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        mailbox: str,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.mailbox = mailbox
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "MailsClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        to: Union[str, List[str]],
        subject: str,
        *,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> SendResult:
        """Send an email.

        Args:
            to: Recipient address or list of addresses.
            subject: Email subject line.
            text: Plain-text body.
            html: HTML body.
            reply_to: Reply-to address.
            attachments: List of attachment dicts with ``filename``, ``content``,
                and optionally ``content_type`` / ``content_id``.

        Returns:
            A :class:`SendResult` with the message id and provider info.
        """
        recipients = [to] if isinstance(to, str) else list(to)
        payload: Dict[str, Any] = {
            "from": self.mailbox,
            "to": recipients,
            "subject": subject,
        }
        if text is not None:
            payload["text"] = text
        if html is not None:
            payload["html"] = html
        if reply_to is not None:
            payload["reply_to"] = reply_to
        if attachments:
            payload["attachments"] = list(attachments)

        response = self._client.post("/api/send", json=payload)
        _handle_error(response)
        data = response.json()
        return SendResult(
            id=data["id"],
            provider=data.get("provider", ""),
            provider_id=data.get("provider_id"),
        )

    def get_inbox(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        direction: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Email]:
        """Fetch emails from the inbox.

        Args:
            limit: Maximum number of emails to return.
            offset: Pagination offset.
            direction: Filter by ``'inbound'`` or ``'outbound'``.
            query: Optional search query string.

        Returns:
            A list of :class:`Email` objects.
        """
        params: Dict[str, Any] = {
            "to": self.mailbox,
            "limit": limit,
            "offset": offset,
        }
        if direction is not None:
            params["direction"] = direction
        if query is not None:
            params["query"] = query

        response = self._client.get("/api/inbox", params=params)
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        direction: Optional[str] = None,
    ) -> List[Email]:
        """Search emails by query string.

        Args:
            query: Search query.
            limit: Maximum number of results.
            direction: Filter by ``'inbound'`` or ``'outbound'``.

        Returns:
            A list of matching :class:`Email` objects.
        """
        return self.get_inbox(query=query, limit=limit, direction=direction)

    def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID.

        Args:
            email_id: The email's unique identifier.

        Returns:
            The :class:`Email` object.

        Raises:
            NotFoundError: If the email does not exist.
        """
        response = self._client.get("/api/email", params={"id": email_id})
        _handle_error(response)
        return _parse_email(response.json())

    def wait_for_code(
        self,
        *,
        timeout: int = 30,
    ) -> Optional[VerificationCode]:
        """Wait for a verification code to arrive.

        This long-polls the server until a code is found or the timeout
        expires.

        Args:
            timeout: Maximum seconds to wait. Defaults to 30.

        Returns:
            A :class:`VerificationCode` if one arrived, or ``None`` on timeout.
        """
        # Use a longer HTTP timeout to cover the server-side polling window.
        response = self._client.get(
            "/api/code",
            params={"to": self.mailbox, "timeout": timeout},
            timeout=max(timeout + 10, 60.0),
        )
        _handle_error(response)
        data = response.json()
        if not data.get("code"):
            return None
        return VerificationCode(
            code=data["code"],
            from_address=data.get("from", ""),
            subject=data.get("subject", ""),
        )

    def delete_email(self, email_id: str) -> bool:
        """Delete an email by ID.

        Args:
            email_id: The email's unique identifier.

        Returns:
            ``True`` if the email was deleted, ``False`` if it was not found.
        """
        response = self._client.delete("/api/email", params={"id": email_id})
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True


# ======================================================================
# Async client
# ======================================================================


class AsyncMailsClient:
    """Asynchronous client for the mails-agent API.

    Mirrors :class:`MailsClient` but all methods are ``async``.

    Args:
        api_url: Worker API base URL.
        token: API key or worker token for authentication.
        mailbox: Your email address.
        timeout: Request timeout in seconds (default 60).
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        mailbox: str,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.mailbox = mailbox
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    async def __aenter__(self) -> "AsyncMailsClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(
        self,
        to: Union[str, List[str]],
        subject: str,
        *,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> SendResult:
        """Send an email. See :meth:`MailsClient.send` for details."""
        recipients = [to] if isinstance(to, str) else list(to)
        payload: Dict[str, Any] = {
            "from": self.mailbox,
            "to": recipients,
            "subject": subject,
        }
        if text is not None:
            payload["text"] = text
        if html is not None:
            payload["html"] = html
        if reply_to is not None:
            payload["reply_to"] = reply_to
        if attachments:
            payload["attachments"] = list(attachments)

        response = await self._client.post("/api/send", json=payload)
        _handle_error(response)
        data = response.json()
        return SendResult(
            id=data["id"],
            provider=data.get("provider", ""),
            provider_id=data.get("provider_id"),
        )

    async def get_inbox(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        direction: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Email]:
        """Fetch emails from the inbox. See :meth:`MailsClient.get_inbox`."""
        params: Dict[str, Any] = {
            "to": self.mailbox,
            "limit": limit,
            "offset": offset,
        }
        if direction is not None:
            params["direction"] = direction
        if query is not None:
            params["query"] = query

        response = await self._client.get("/api/inbox", params=params)
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        direction: Optional[str] = None,
    ) -> List[Email]:
        """Search emails by query. See :meth:`MailsClient.search`."""
        return await self.get_inbox(query=query, limit=limit, direction=direction)

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID. See :meth:`MailsClient.get_email`."""
        response = await self._client.get("/api/email", params={"id": email_id})
        _handle_error(response)
        return _parse_email(response.json())

    async def wait_for_code(
        self,
        *,
        timeout: int = 30,
    ) -> Optional[VerificationCode]:
        """Wait for a verification code. See :meth:`MailsClient.wait_for_code`."""
        response = await self._client.get(
            "/api/code",
            params={"to": self.mailbox, "timeout": timeout},
            timeout=max(timeout + 10, 60.0),
        )
        _handle_error(response)
        data = response.json()
        if not data.get("code"):
            return None
        return VerificationCode(
            code=data["code"],
            from_address=data.get("from", ""),
            subject=data.get("subject", ""),
        )

    async def delete_email(self, email_id: str) -> bool:
        """Delete an email by ID. See :meth:`MailsClient.delete_email`."""
        response = await self._client.delete("/api/email", params={"id": email_id})
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True
