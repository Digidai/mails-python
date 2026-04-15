"""Synchronous and asynchronous HTTP clients for the mails-agent API."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, Generator, Iterator, List, Optional, Sequence, Union

import httpx

from .exceptions import ApiError, AuthError, NotFoundError
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

_VALID_EXTRACT_TYPES = {"order", "shipping", "calendar", "receipt", "code"}
_VALID_SEARCH_MODES = {"keyword", "semantic", "hybrid"}
_UNSET = object()  # Sentinel to distinguish "not provided" from None


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_attachment(data: Dict[str, Any]) -> Attachment:
    """Convert a raw API dict into an Attachment dataclass."""
    if "id" not in data:
        raise ApiError(f"Attachment missing required 'id' field: {data!r}", 422)
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
    if "thread_id" not in data:
        raise ApiError(f"Thread missing required 'thread_id' field: {data!r}", 422)
    if "latest_email_id" not in data:
        raise ApiError(f"Thread missing required 'latest_email_id' field: {data!r}", 422)
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
    if "id" not in data:
        raise ApiError(f"Email missing required 'id' field: {data!r}", 422)
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


def _parse_dns_record(data: Dict[str, Any]) -> DnsRecord:
    """Convert a raw API dict into a DnsRecord dataclass."""
    return DnsRecord(
        type=data.get("type", ""),
        host=data.get("host", ""),
        value=data.get("value", ""),
        purpose=data.get("purpose", ""),
        priority=data.get("priority"),
    )


def _parse_dns_records(data: Optional[Dict[str, Any]]) -> Optional[DnsRecords]:
    """Convert a raw API dict into a DnsRecords dataclass."""
    if not data or not isinstance(data, dict):
        return None
    return DnsRecords(
        mx=_parse_dns_record(data["mx"]) if "mx" in data else None,
        spf=_parse_dns_record(data["spf"]) if "spf" in data else None,
        dmarc=_parse_dns_record(data["dmarc"]) if "dmarc" in data else None,
    )


def _parse_domain(data: Dict[str, Any]) -> Domain:
    """Convert a raw API dict into a Domain dataclass."""
    return Domain(
        id=data.get("id", ""),
        domain=data.get("domain", ""),
        status=data.get("status", ""),
        mx_verified=bool(data.get("mx_verified", False)),
        spf_verified=bool(data.get("spf_verified", False)),
        dkim_verified=bool(data.get("dkim_verified", False)),
        created_at=data.get("created_at", ""),
        verified_at=data.get("verified_at"),
        dns_records=_parse_dns_records(data.get("dns_records")),
        instructions=data.get("instructions"),
    )


def _parse_webhook_route(data: Dict[str, Any]) -> WebhookRoute:
    """Convert a raw API dict into a WebhookRoute dataclass."""
    return WebhookRoute(
        label=data.get("label", ""),
        webhook_url=data.get("webhook_url", ""),
        created_at=data.get("created_at", ""),
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
        api_url: Worker API base URL (e.g. ``https://api.mails0.com``).
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
        from_address: Optional[str] = None,
        cc: Optional[Union[str, List[str]]] = None,
        bcc: Optional[Union[str, List[str]]] = None,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> SendResult:
        """Send an email.

        Args:
            to: Recipient address or list of addresses.
            subject: Email subject line.
            from_address: Sender address, e.g. ``"Display Name <user@example.com>"``.
                Defaults to *mailbox*. The server enforces that the email
                portion matches your mailbox.
            cc: CC recipient(s).
            bcc: BCC recipient(s).
            text: Plain-text body.
            html: HTML body.
            reply_to: Reply-to address.
            in_reply_to: Message-ID of the email being replied to (for threading).
            headers: Extra email headers.
            attachments: List of attachment dicts with ``filename``, ``content``,
                and optionally ``content_type`` / ``content_id``.

        Returns:
            A :class:`SendResult` with the message id, provider info, and thread id.
        """
        recipients = [to] if isinstance(to, str) else list(to)
        payload: Dict[str, Any] = {
            "from": from_address or self.mailbox,
            "to": recipients,
            "subject": subject,
        }
        if cc is not None:
            payload["cc"] = [cc] if isinstance(cc, str) else list(cc)
        if bcc is not None:
            payload["bcc"] = [bcc] if isinstance(bcc, str) else list(bcc)
        if text is not None:
            payload["text"] = text
        if html is not None:
            payload["html"] = html
        if reply_to is not None:
            payload["reply_to"] = reply_to
        if in_reply_to is not None:
            payload["in_reply_to"] = in_reply_to
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
            thread_id=data.get("thread_id"),
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
        capped_timeout = min(timeout, 300)  # Server max is 300s
        params: Dict[str, Any] = {"timeout": capped_timeout}
        if not self.hosted:
            params["to"] = self.mailbox
        if since is not None:
            params["since"] = since

        # Use a longer HTTP timeout to cover the server-side polling window.
        response = self._client.get(
            f"{self._prefix}/code",
            params=params,
            timeout=max(capped_timeout + 10, 60.0),
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

    def get_stats(self) -> MailboxStats:
        """Fetch mailbox statistics.

        Returns:
            A :class:`MailboxStats` with email counts.
        """
        params: Dict[str, Any] = {}
        if not self.hosted:
            params["to"] = self.mailbox
        response = self._client.get(f"{self._prefix}/stats", params=params)
        _handle_error(response)
        data = response.json()
        raw_ingest = data.get("ingest")
        ingest = IngestStats(
            pending=_safe_int(raw_ingest.get("pending")),
            parsed=_safe_int(raw_ingest.get("parsed")),
            failed=_safe_int(raw_ingest.get("failed")),
        ) if isinstance(raw_ingest, dict) else None
        return MailboxStats(
            mailbox=data.get("mailbox", self.mailbox),
            total_emails=_safe_int(data.get("total_emails")),
            inbound=_safe_int(data.get("inbound")),
            outbound=_safe_int(data.get("outbound")),
            emails_this_month=_safe_int(data.get("emails_this_month")),
            ingest=ingest,
            suppression_count=_safe_int(data.get("suppression_count")),
            webhook_routes=_safe_int(data.get("webhook_routes")),
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

    # ------------------------------------------------------------------
    # Domain management
    # ------------------------------------------------------------------

    def get_domains(self) -> List[Domain]:
        """List all custom domains.

        Returns:
            A list of :class:`Domain` objects.
        """
        response = self._client.get(f"{self._prefix}/domains")
        _handle_error(response)
        data = response.json()
        return [_parse_domain(d) for d in data.get("domains", [])]

    def add_domain(self, domain: str) -> Domain:
        """Register a new custom domain.

        Args:
            domain: The domain name to register (e.g. ``'example.com'``).

        Returns:
            A :class:`Domain` with DNS records and setup instructions.
        """
        response = self._client.post(
            f"{self._prefix}/domains", json={"domain": domain}
        )
        _handle_error(response)
        return _parse_domain(response.json())

    def get_domain(self, domain_id: str) -> Domain:
        """Fetch a domain by ID.

        Args:
            domain_id: The domain's unique identifier.

        Returns:
            A :class:`Domain` with DNS records.

        Raises:
            NotFoundError: If the domain does not exist.
        """
        response = self._client.get(f"{self._prefix}/domains/{domain_id}")
        _handle_error(response)
        return _parse_domain(response.json())

    def verify_domain(self, domain_id: str) -> DomainVerification:
        """Trigger DNS verification for a domain.

        Args:
            domain_id: The domain's unique identifier.

        Returns:
            A :class:`DomainVerification` with verification results.
        """
        response = self._client.post(
            f"{self._prefix}/domains/{domain_id}/verify"
        )
        _handle_error(response)
        data = response.json()
        return DomainVerification(
            id=data.get("id", ""),
            domain=data.get("domain", ""),
            status=data.get("status", ""),
            mx_verified=bool(data.get("mx_verified", False)),
            spf_verified=bool(data.get("spf_verified", False)),
            message=data.get("message", ""),
        )

    def delete_domain(self, domain_id: str) -> bool:
        """Delete a custom domain.

        Args:
            domain_id: The domain's unique identifier.

        Returns:
            ``True`` if deleted successfully.
        """
        response = self._client.delete(f"{self._prefix}/domains/{domain_id}")
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    # ------------------------------------------------------------------
    # Mailbox management
    # ------------------------------------------------------------------

    def get_mailbox(self) -> Mailbox:
        """Fetch mailbox info and status.

        Returns:
            A :class:`Mailbox` with status and webhook configuration.
        """
        response = self._client.get(f"{self._prefix}/mailbox")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
            webhook_url=data.get("webhook_url"),
            created_at=data.get("created_at", ""),
        )

    def update_mailbox(
        self, *, webhook_url: Union[Optional[str], object] = _UNSET
    ) -> Mailbox:
        """Update mailbox settings.

        Args:
            webhook_url: Webhook URL for email notifications. Pass ``None``
                to clear the webhook. Omit to leave unchanged.

        Returns:
            Updated :class:`Mailbox`.
        """
        payload: Dict[str, Any] = {}
        if webhook_url is not _UNSET:
            payload["webhook_url"] = webhook_url
        response = self._client.patch(
            f"{self._prefix}/mailbox", json=payload
        )
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
            webhook_url=data.get("webhook_url"),
            created_at=data.get("created_at", ""),
        )

    def delete_mailbox(self) -> MailboxDeleteResult:
        """Delete the mailbox and all associated data.

        Returns:
            A :class:`MailboxDeleteResult` with cleanup details.
        """
        response = self._client.delete(f"{self._prefix}/mailbox")
        _handle_error(response)
        data = response.json()
        return MailboxDeleteResult(
            ok=bool(data.get("ok", False)),
            deleted=data.get("deleted", ""),
            r2_blobs_deleted=_safe_int(data.get("r2_blobs_deleted")),
        )

    def pause_mailbox(self) -> Mailbox:
        """Pause the mailbox (stops receiving emails).

        Returns:
            Updated :class:`Mailbox` with ``status='paused'``.
        """
        response = self._client.patch(f"{self._prefix}/mailbox/pause")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
        )

    def resume_mailbox(self) -> Mailbox:
        """Resume the mailbox (start receiving emails again).

        Returns:
            Updated :class:`Mailbox` with ``status='active'``.
        """
        response = self._client.patch(f"{self._prefix}/mailbox/resume")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
        )

    # ------------------------------------------------------------------
    # Webhook routes
    # ------------------------------------------------------------------

    def get_webhook_routes(self) -> WebhookRouteList:
        """List label-specific webhook routes.

        Returns:
            A :class:`WebhookRouteList` with all configured routes.
        """
        response = self._client.get(f"{self._prefix}/mailbox/routes")
        _handle_error(response)
        data = response.json()
        return WebhookRouteList(
            mailbox=data.get("mailbox", ""),
            routes=[_parse_webhook_route(r) for r in data.get("routes", [])],
        )

    def set_webhook_route(self, label: str, webhook_url: str) -> WebhookRoute:
        """Create or update a webhook route for a label.

        Args:
            label: The email label (e.g. ``'code'``, ``'newsletter'``,
                ``'notification'``, ``'personal'``).
            webhook_url: The URL to receive webhook notifications.

        Returns:
            The created/updated :class:`WebhookRoute`.
        """
        response = self._client.put(
            f"{self._prefix}/mailbox/routes",
            json={"label": label, "webhook_url": webhook_url},
        )
        _handle_error(response)
        data = response.json()
        return WebhookRoute(
            label=data.get("label", ""),
            webhook_url=data.get("webhook_url", ""),
        )

    def delete_webhook_route(self, label: str) -> bool:
        """Delete a webhook route for a label.

        Args:
            label: The label whose route should be deleted.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        response = self._client.delete(
            f"{self._prefix}/mailbox/routes", params={"label": label}
        )
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    # ------------------------------------------------------------------
    # Claim and health
    # ------------------------------------------------------------------

    def claim_mailbox(self, name: str) -> ClaimResult:
        """Claim a new mailbox (headless, no web UI required).

        Args:
            name: The desired mailbox name (e.g. ``'my-agent'``).

        Returns:
            A :class:`ClaimResult` with the mailbox address and API key.
        """
        response = self._client.post(
            f"{self._prefix}/claim/auto", json={"name": name}
        )
        _handle_error(response)
        data = response.json()
        return ClaimResult(
            mailbox=data.get("mailbox", ""),
            api_key=data.get("api_key", ""),
        )

    # ------------------------------------------------------------------
    # SSE Events
    # ------------------------------------------------------------------

    def get_events(
        self,
        *,
        mailbox: Optional[str] = None,
        types: Optional[str] = None,
        since: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Stream real-time events via Server-Sent Events.

        Yields parsed event dicts. Each dict has ``event`` (event type)
        and ``data`` (parsed JSON payload) keys.

        Args:
            mailbox: Filter events to a specific mailbox.
            types: Comma-separated event types to subscribe to.
            since: Only receive events after this ISO 8601 timestamp.

        Yields:
            Dicts with ``event`` and ``data`` keys.
        """
        params: Dict[str, Any] = {}
        if mailbox is not None:
            params["mailbox"] = mailbox
        if types is not None:
            params["types"] = types
        if since is not None:
            params["since"] = since

        with self._client.stream(
            "GET", f"{self._prefix}/events", params=params
        ) as response:
            _handle_error(response)
            event_type = "message"
            data_lines: List[str] = []
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "" and data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        parsed = json.loads(raw)
                    except (ValueError, TypeError):
                        parsed = raw
                    yield {"event": event_type, "data": parsed}
                    event_type = "message"
                    data_lines = []

    def health(self) -> bool:
        """Check if the Worker is healthy.

        Returns:
            ``True`` if the server responds, ``False`` on error.
        """
        try:
            response = self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False


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
        from_address: Optional[str] = None,
        cc: Optional[Union[str, List[str]]] = None,
        bcc: Optional[Union[str, List[str]]] = None,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        attachments: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> SendResult:
        """Send an email. See :meth:`MailsClient.send` for details."""
        recipients = [to] if isinstance(to, str) else list(to)
        payload: Dict[str, Any] = {
            "from": from_address or self.mailbox,
            "to": recipients,
            "subject": subject,
        }
        if cc is not None:
            payload["cc"] = [cc] if isinstance(cc, str) else list(cc)
        if bcc is not None:
            payload["bcc"] = [bcc] if isinstance(bcc, str) else list(bcc)
        if text is not None:
            payload["text"] = text
        if html is not None:
            payload["html"] = html
        if reply_to is not None:
            payload["reply_to"] = reply_to
        if in_reply_to is not None:
            payload["in_reply_to"] = in_reply_to
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
            thread_id=data.get("thread_id"),
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
        capped_timeout = min(timeout, 300)
        params: Dict[str, Any] = {"timeout": capped_timeout}
        if not self.hosted:
            params["to"] = self.mailbox
        if since is not None:
            params["since"] = since

        response = await self._client.get(
            f"{self._prefix}/code",
            params=params,
            timeout=max(capped_timeout + 10, 60.0),
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

    async def get_stats(self) -> MailboxStats:
        """Fetch mailbox statistics. See :meth:`MailsClient.get_stats`."""
        params: Dict[str, Any] = {}
        if not self.hosted:
            params["to"] = self.mailbox
        response = await self._client.get(f"{self._prefix}/stats", params=params)
        _handle_error(response)
        data = response.json()
        raw_ingest = data.get("ingest")
        ingest = IngestStats(
            pending=_safe_int(raw_ingest.get("pending")),
            parsed=_safe_int(raw_ingest.get("parsed")),
            failed=_safe_int(raw_ingest.get("failed")),
        ) if isinstance(raw_ingest, dict) else None
        return MailboxStats(
            mailbox=data.get("mailbox", self.mailbox),
            total_emails=_safe_int(data.get("total_emails")),
            inbound=_safe_int(data.get("inbound")),
            outbound=_safe_int(data.get("outbound")),
            emails_this_month=_safe_int(data.get("emails_this_month")),
            ingest=ingest,
            suppression_count=_safe_int(data.get("suppression_count")),
            webhook_routes=_safe_int(data.get("webhook_routes")),
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

    # ------------------------------------------------------------------
    # Domain management
    # ------------------------------------------------------------------

    async def get_domains(self) -> List[Domain]:
        """List all custom domains. See :meth:`MailsClient.get_domains`."""
        response = await self._client.get(f"{self._prefix}/domains")
        _handle_error(response)
        data = response.json()
        return [_parse_domain(d) for d in data.get("domains", [])]

    async def add_domain(self, domain: str) -> Domain:
        """Register a new custom domain. See :meth:`MailsClient.add_domain`."""
        response = await self._client.post(
            f"{self._prefix}/domains", json={"domain": domain}
        )
        _handle_error(response)
        return _parse_domain(response.json())

    async def get_domain(self, domain_id: str) -> Domain:
        """Fetch a domain by ID. See :meth:`MailsClient.get_domain`."""
        response = await self._client.get(f"{self._prefix}/domains/{domain_id}")
        _handle_error(response)
        return _parse_domain(response.json())

    async def verify_domain(self, domain_id: str) -> DomainVerification:
        """Trigger DNS verification. See :meth:`MailsClient.verify_domain`."""
        response = await self._client.post(
            f"{self._prefix}/domains/{domain_id}/verify"
        )
        _handle_error(response)
        data = response.json()
        return DomainVerification(
            id=data.get("id", ""),
            domain=data.get("domain", ""),
            status=data.get("status", ""),
            mx_verified=bool(data.get("mx_verified", False)),
            spf_verified=bool(data.get("spf_verified", False)),
            message=data.get("message", ""),
        )

    async def delete_domain(self, domain_id: str) -> bool:
        """Delete a custom domain. See :meth:`MailsClient.delete_domain`."""
        response = await self._client.delete(f"{self._prefix}/domains/{domain_id}")
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    # ------------------------------------------------------------------
    # Mailbox management
    # ------------------------------------------------------------------

    async def get_mailbox(self) -> Mailbox:
        """Fetch mailbox info. See :meth:`MailsClient.get_mailbox`."""
        response = await self._client.get(f"{self._prefix}/mailbox")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
            webhook_url=data.get("webhook_url"),
            created_at=data.get("created_at", ""),
        )

    async def update_mailbox(
        self, *, webhook_url: Union[Optional[str], object] = _UNSET
    ) -> Mailbox:
        """Update mailbox settings. See :meth:`MailsClient.update_mailbox`."""
        payload: Dict[str, Any] = {}
        if webhook_url is not _UNSET:
            payload["webhook_url"] = webhook_url
        response = await self._client.patch(
            f"{self._prefix}/mailbox", json=payload
        )
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
            webhook_url=data.get("webhook_url"),
            created_at=data.get("created_at", ""),
        )

    async def delete_mailbox(self) -> MailboxDeleteResult:
        """Delete the mailbox. See :meth:`MailsClient.delete_mailbox`."""
        response = await self._client.delete(f"{self._prefix}/mailbox")
        _handle_error(response)
        data = response.json()
        return MailboxDeleteResult(
            ok=bool(data.get("ok", False)),
            deleted=data.get("deleted", ""),
            r2_blobs_deleted=_safe_int(data.get("r2_blobs_deleted")),
        )

    async def pause_mailbox(self) -> Mailbox:
        """Pause the mailbox. See :meth:`MailsClient.pause_mailbox`."""
        response = await self._client.patch(f"{self._prefix}/mailbox/pause")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
        )

    async def resume_mailbox(self) -> Mailbox:
        """Resume the mailbox. See :meth:`MailsClient.resume_mailbox`."""
        response = await self._client.patch(f"{self._prefix}/mailbox/resume")
        _handle_error(response)
        data = response.json()
        return Mailbox(
            mailbox=data.get("mailbox", ""),
            status=data.get("status", ""),
        )

    # ------------------------------------------------------------------
    # Webhook routes
    # ------------------------------------------------------------------

    async def get_webhook_routes(self) -> WebhookRouteList:
        """List webhook routes. See :meth:`MailsClient.get_webhook_routes`."""
        response = await self._client.get(f"{self._prefix}/mailbox/routes")
        _handle_error(response)
        data = response.json()
        return WebhookRouteList(
            mailbox=data.get("mailbox", ""),
            routes=[_parse_webhook_route(r) for r in data.get("routes", [])],
        )

    async def set_webhook_route(self, label: str, webhook_url: str) -> WebhookRoute:
        """Create/update a webhook route. See :meth:`MailsClient.set_webhook_route`."""
        response = await self._client.put(
            f"{self._prefix}/mailbox/routes",
            json={"label": label, "webhook_url": webhook_url},
        )
        _handle_error(response)
        data = response.json()
        return WebhookRoute(
            label=data.get("label", ""),
            webhook_url=data.get("webhook_url", ""),
        )

    async def delete_webhook_route(self, label: str) -> bool:
        """Delete a webhook route. See :meth:`MailsClient.delete_webhook_route`."""
        response = await self._client.delete(
            f"{self._prefix}/mailbox/routes", params={"label": label}
        )
        if response.status_code == 404:
            return False
        _handle_error(response)
        return True

    # ------------------------------------------------------------------
    # Claim and health
    # ------------------------------------------------------------------

    async def claim_mailbox(self, name: str) -> ClaimResult:
        """Claim a new mailbox. See :meth:`MailsClient.claim_mailbox`."""
        response = await self._client.post(
            f"{self._prefix}/claim/auto", json={"name": name}
        )
        _handle_error(response)
        data = response.json()
        return ClaimResult(
            mailbox=data.get("mailbox", ""),
            api_key=data.get("api_key", ""),
        )

    async def health(self) -> bool:
        """Check if the Worker is healthy. See :meth:`MailsClient.health`."""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # SSE Events
    # ------------------------------------------------------------------

    async def get_events(
        self,
        *,
        mailbox: Optional[str] = None,
        types: Optional[str] = None,
        since: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream real-time events via SSE. See :meth:`MailsClient.get_events`."""
        params: Dict[str, Any] = {}
        if mailbox is not None:
            params["mailbox"] = mailbox
        if types is not None:
            params["types"] = types
        if since is not None:
            params["since"] = since

        async with self._client.stream(
            "GET", f"{self._prefix}/events", params=params
        ) as response:
            _handle_error(response)
            event_type = "message"
            data_lines: List[str] = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "" and data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        parsed = json.loads(raw)
                    except (ValueError, TypeError):
                        parsed = raw
                    yield {"event": event_type, "data": parsed}
                    event_type = "message"
                    data_lines = []
