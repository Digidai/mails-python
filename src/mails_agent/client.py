"""Synchronous and asynchronous HTTP clients for the mails-agent API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

import httpx

from .exceptions import ApiError, AuthError, NotFoundError
from .models import Attachment, Email, EmailThread, MeInfo, SendResult, VerificationCode

_VALID_EXTRACT_TYPES = {"order", "shipping", "calendar", "receipt", "code"}
_VALID_SEARCH_MODES = {"keyword", "semantic", "hybrid"}


def _parse_attachment(data: Dict[str, Any]) -> Attachment:
    """Convert a raw API dict into an Attachment dataclass."""
    return Attachment(
        id=data["id"],
        email_id=data.get("email_id", ""),
        filename=data.get("filename", ""),
        content_type=data.get("content_type", ""),
        size_bytes=data.get("size_bytes"),
        content_disposition=data.get("content_disposition"),
        content_id=data.get("content_id"),
        mime_part_index=int(data.get("mime_part_index", 0)),
        text_content=data.get("text_content", ""),
        text_extraction_status=data.get("text_extraction_status", "pending"),
        storage_key=data.get("storage_key"),
        downloadable=bool(data.get("downloadable", False)),
        created_at=data.get("created_at", ""),
    )


def _parse_thread(data: Dict[str, Any]) -> EmailThread:
    """Convert a raw API dict into an EmailThread dataclass."""
    return EmailThread(
        thread_id=data["thread_id"],
        latest_email_id=data["latest_email_id"],
        subject=data.get("subject", ""),
        from_address=data.get("from_address", ""),
        from_name=data.get("from_name", ""),
        received_at=data.get("received_at", ""),
        message_count=int(data.get("message_count", 0)),
        has_attachments=bool(data.get("has_attachments", False)),
        code=data.get("code"),
    )


def _parse_email(data: Dict[str, Any]) -> Email:
    """Convert a raw API dict into an Email dataclass."""
    raw_attachments = data.get("attachments")
    attachments = (
        [_parse_attachment(a) for a in raw_attachments]
        if isinstance(raw_attachments, list)
        else []
    )
    raw_labels = data.get("labels")
    labels = list(raw_labels) if isinstance(raw_labels, list) else []
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
        to_address=data.get("to_address", ""),
        headers=data.get("headers") if isinstance(data.get("headers"), dict) else {},
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        message_id=data.get("message_id"),
        attachment_names=data.get("attachment_names", ""),
        attachment_search_text=data.get("attachment_search_text", ""),
        raw_storage_key=data.get("raw_storage_key"),
        attachments=attachments,
        created_at=data.get("created_at", ""),
        thread_id=data.get("thread_id"),
        in_reply_to=data.get("in_reply_to"),
        references=data.get("references"),
        labels=labels,
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


def _api_prefix(is_v1: bool) -> str:
    """Return the route prefix for the current mode."""
    return "/v1" if is_v1 else "/api"


class MailsClient:
    """Synchronous client for the mails-agent API.

    Args:
        api_url: Worker API base URL (e.g. ``https://mails-worker.genedai.workers.dev``).
        token: API key or worker token for authentication.
        mailbox: Your email address (e.g. ``agent@mails0.com``).
        timeout: Request timeout in seconds. Defaults to 60 to accommodate
            long-polling ``wait_for_code`` calls.
        hosted: When ``True``, use ``/v1/*`` routes (hosted mode) instead of
            ``/api/*`` (self-hosted). In hosted mode the mailbox is bound to
            the token, so the ``?to=`` parameter is not sent.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        mailbox: str,
        *,
        timeout: float = 60.0,
        hosted: bool = False,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.mailbox = mailbox
        self.hosted = hosted
        self._prefix = _api_prefix(hosted)
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
        headers: Optional[Dict[str, str]] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> SendResult:
        """Send an email.

        Args:
            to: Recipient address or list of addresses.
            subject: Email subject line.
            text: Plain-text body.
            html: HTML body.
            reply_to: Reply-to address.
            headers: Extra email headers.
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
        if headers:
            payload["headers"] = headers
        if attachments:
            payload["attachments"] = list(attachments)

        response = self._client.post(f"{self._prefix}/send", json=payload)
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
        label: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[Email]:
        """Fetch emails from the inbox.

        Args:
            limit: Maximum number of emails to return.
            offset: Pagination offset.
            direction: Filter by ``'inbound'`` or ``'outbound'``.
            query: Optional search query string.
            label: Optional label filter (e.g. ``'newsletter'``, ``'notification'``).
            mode: Search mode — ``'keyword'``, ``'semantic'``, or ``'hybrid'``.
                Only meaningful when *query* is provided.

        Returns:
            A list of :class:`Email` objects.

        Raises:
            ValueError: If *mode* is not a valid search mode.
        """
        if mode is not None and mode not in _VALID_SEARCH_MODES:
            raise ValueError(
                f"Invalid search mode {mode!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_SEARCH_MODES))}"
            )
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        # In self-hosted mode (/api/*), pass ?to= for mailbox filtering.
        # In hosted mode (/v1/*), the mailbox is bound to the token.
        if not self.hosted:
            params["to"] = self.mailbox
        if direction is not None:
            params["direction"] = direction
        if query is not None:
            params["query"] = query
        if label is not None:
            params["label"] = label
        if mode is not None:
            params["mode"] = mode

        response = self._client.get(f"{self._prefix}/inbox", params=params)
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        direction: Optional[str] = None,
        label: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[Email]:
        """Search emails by query string.

        Args:
            query: Search query.
            limit: Maximum number of results.
            direction: Filter by ``'inbound'`` or ``'outbound'``.
            label: Optional label filter.
            mode: Search mode — ``'keyword'``, ``'semantic'``, or ``'hybrid'``.

        Returns:
            A list of matching :class:`Email` objects.
        """
        return self.get_inbox(query=query, limit=limit, direction=direction, label=label, mode=mode)

    def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID.

        Args:
            email_id: The email's unique identifier.

        Returns:
            The :class:`Email` object.

        Raises:
            NotFoundError: If the email does not exist.
        """
        response = self._client.get(
            f"{self._prefix}/email", params={"id": email_id}
        )
        _handle_error(response)
        return _parse_email(response.json())

    def wait_for_code(
        self,
        *,
        timeout: int = 30,
        since: Optional[str] = None,
    ) -> Optional[VerificationCode]:
        """Wait for a verification code to arrive.

        This long-polls the server until a code is found or the timeout
        expires.

        Args:
            timeout: Maximum seconds to wait. Defaults to 30.
            since: Only consider emails received after this ISO 8601 timestamp.

        Returns:
            A :class:`VerificationCode` if one arrived, or ``None`` on timeout.
        """
        params: Dict[str, Any] = {"timeout": timeout}
        if not self.hosted:
            params["to"] = self.mailbox
        if since is not None:
            params["since"] = since

        # Use a longer HTTP timeout to cover the server-side polling window.
        response = self._client.get(
            f"{self._prefix}/code",
            params=params,
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
            id=data.get("id"),
            received_at=data.get("received_at"),
        )

    def delete_email(self, email_id: str) -> bool:
        """Delete an email by ID.

        Args:
            email_id: The email's unique identifier.

        Returns:
            ``True`` if the email was deleted, ``False`` if it was not found.
        """
        response = self._client.delete(
            f"{self._prefix}/email", params={"id": email_id}
        )
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    def get_attachment(self, attachment_id: str) -> bytes:
        """Download an attachment by ID.

        Args:
            attachment_id: The attachment's unique identifier.

        Returns:
            The raw attachment bytes.

        Raises:
            NotFoundError: If the attachment does not exist.
        """
        response = self._client.get(
            f"{self._prefix}/attachment", params={"id": attachment_id}
        )
        _handle_error(response)
        return response.content

    def get_me(self) -> MeInfo:
        """Fetch information about the current authentication context.

        Returns:
            A :class:`MeInfo` with worker name, mailbox, and send capability.
        """
        response = self._client.get(f"{self._prefix}/me")
        _handle_error(response)
        data = response.json()
        return MeInfo(
            worker=data.get("worker", ""),
            mailbox=data.get("mailbox"),
            send=bool(data.get("send", False)),
        )

    def get_threads(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> List[EmailThread]:
        """Fetch conversation threads.

        Args:
            limit: Maximum number of threads to return.
            offset: Pagination offset.

        Returns:
            A list of :class:`EmailThread` objects.
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if not self.hosted:
            params["to"] = self.mailbox

        response = self._client.get(f"{self._prefix}/threads", params=params)
        _handle_error(response)
        data = response.json()
        return [_parse_thread(t) for t in data.get("threads", [])]

    def get_thread(self, thread_id: str) -> List[Email]:
        """Fetch all emails in a conversation thread.

        Args:
            thread_id: The thread's unique identifier.

        Returns:
            A list of :class:`Email` objects in chronological order.

        Raises:
            NotFoundError: If the thread does not exist.
        """
        params: Dict[str, Any] = {"id": thread_id}
        if not self.hosted:
            params["to"] = self.mailbox

        response = self._client.get(f"{self._prefix}/thread", params=params)
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    def extract(self, email_id: str, type: str) -> dict:
        """Extract structured data from an email.

        Args:
            email_id: The email's unique identifier.
            type: Extraction type. Must be one of ``'order'``, ``'shipping'``,
                ``'calendar'``, ``'receipt'``, or ``'code'``.

        Returns:
            A dict with ``email_id`` and ``extraction`` keys.

        Raises:
            ValueError: If *type* is not a valid extraction type.
            NotFoundError: If the email does not exist.
        """
        if type not in _VALID_EXTRACT_TYPES:
            raise ValueError(
                f"Invalid extraction type {type!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_EXTRACT_TYPES))}"
            )
        payload = {"email_id": email_id, "type": type}
        response = self._client.post(f"{self._prefix}/extract", json=payload)
        _handle_error(response)
        return response.json()


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
        hosted: When ``True``, use ``/v1/*`` routes (hosted mode).
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        mailbox: str,
        *,
        timeout: float = 60.0,
        hosted: bool = False,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.mailbox = mailbox
        self.hosted = hosted
        self._prefix = _api_prefix(hosted)
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
        headers: Optional[Dict[str, str]] = None,
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
        if headers:
            payload["headers"] = headers
        if attachments:
            payload["attachments"] = list(attachments)

        response = await self._client.post(
            f"{self._prefix}/send", json=payload
        )
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
        label: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[Email]:
        """Fetch emails from the inbox. See :meth:`MailsClient.get_inbox`."""
        if mode is not None and mode not in _VALID_SEARCH_MODES:
            raise ValueError(
                f"Invalid search mode {mode!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_SEARCH_MODES))}"
            )
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if not self.hosted:
            params["to"] = self.mailbox
        if direction is not None:
            params["direction"] = direction
        if query is not None:
            params["query"] = query
        if label is not None:
            params["label"] = label
        if mode is not None:
            params["mode"] = mode

        response = await self._client.get(
            f"{self._prefix}/inbox", params=params
        )
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        direction: Optional[str] = None,
        label: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[Email]:
        """Search emails by query. See :meth:`MailsClient.search`."""
        return await self.get_inbox(query=query, limit=limit, direction=direction, label=label, mode=mode)

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID. See :meth:`MailsClient.get_email`."""
        response = await self._client.get(
            f"{self._prefix}/email", params={"id": email_id}
        )
        _handle_error(response)
        return _parse_email(response.json())

    async def wait_for_code(
        self,
        *,
        timeout: int = 30,
        since: Optional[str] = None,
    ) -> Optional[VerificationCode]:
        """Wait for a verification code. See :meth:`MailsClient.wait_for_code`."""
        params: Dict[str, Any] = {"timeout": timeout}
        if not self.hosted:
            params["to"] = self.mailbox
        if since is not None:
            params["since"] = since

        response = await self._client.get(
            f"{self._prefix}/code",
            params=params,
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
            id=data.get("id"),
            received_at=data.get("received_at"),
        )

    async def delete_email(self, email_id: str) -> bool:
        """Delete an email by ID. See :meth:`MailsClient.delete_email`."""
        response = await self._client.delete(
            f"{self._prefix}/email", params={"id": email_id}
        )
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    async def get_attachment(self, attachment_id: str) -> bytes:
        """Download an attachment by ID. See :meth:`MailsClient.get_attachment`."""
        response = await self._client.get(
            f"{self._prefix}/attachment", params={"id": attachment_id}
        )
        _handle_error(response)
        return response.content

    async def get_me(self) -> MeInfo:
        """Fetch auth context info. See :meth:`MailsClient.get_me`."""
        response = await self._client.get(f"{self._prefix}/me")
        _handle_error(response)
        data = response.json()
        return MeInfo(
            worker=data.get("worker", ""),
            mailbox=data.get("mailbox"),
            send=bool(data.get("send", False)),
        )

    async def get_threads(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> List[EmailThread]:
        """Fetch conversation threads. See :meth:`MailsClient.get_threads`."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if not self.hosted:
            params["to"] = self.mailbox

        response = await self._client.get(
            f"{self._prefix}/threads", params=params
        )
        _handle_error(response)
        data = response.json()
        return [_parse_thread(t) for t in data.get("threads", [])]

    async def get_thread(self, thread_id: str) -> List[Email]:
        """Fetch all emails in a thread. See :meth:`MailsClient.get_thread`."""
        params: Dict[str, Any] = {"id": thread_id}
        if not self.hosted:
            params["to"] = self.mailbox

        response = await self._client.get(
            f"{self._prefix}/thread", params=params
        )
        _handle_error(response)
        data = response.json()
        return [_parse_email(e) for e in data.get("emails", [])]

    async def extract(self, email_id: str, type: str) -> dict:
        """Extract structured data from an email. See :meth:`MailsClient.extract`."""
        if type not in _VALID_EXTRACT_TYPES:
            raise ValueError(
                f"Invalid extraction type {type!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_EXTRACT_TYPES))}"
            )
        payload = {"email_id": email_id, "type": type}
        response = await self._client.post(
            f"{self._prefix}/extract", json=payload
        )
        _handle_error(response)
        return response.json()
