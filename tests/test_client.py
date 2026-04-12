"""Tests for MailsClient and AsyncMailsClient."""

from __future__ import annotations

import json

import httpx
import pytest

from mails_agent import (
    ApiError,
    AsyncMailsClient,
    Attachment,
    AuthError,
    Email,
    EmailThread,
    MailboxStats,
    MailsClient,
    MailsError,
    MeInfo,
    NotFoundError,
    SendResult,
    VerificationCode,
)
from mails_agent.client import (
    _handle_error,
    _parse_attachment,
    _parse_email,
    _parse_thread,
    _safe_int,
)

API_URL = "https://mails-worker.example.com"
TOKEN = "test-token"
MAILBOX = "agent@mails0.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(*, hosted: bool = False) -> MailsClient:
    return MailsClient(API_URL, TOKEN, MAILBOX, hosted=hosted)


def _email_dict(**overrides: object) -> dict:
    base = {
        "id": "email-1",
        "mailbox": MAILBOX,
        "from_address": "sender@example.com",
        "from_name": "Sender",
        "subject": "Hello",
        "direction": "inbound",
        "status": "received",
        "received_at": "2024-01-01T00:00:00Z",
        "has_attachments": False,
        "attachment_count": 0,
        "body_text": "Hi there",
        "body_html": "<p>Hi there</p>",
        "code": None,
    }
    base.update(overrides)
    return base


def _full_email_dict(**overrides: object) -> dict:
    """An email dict as returned by the /api/email detail endpoint."""
    base = _email_dict()
    base.update({
        "to_address": MAILBOX,
        "headers": {"X-Test": "1"},
        "metadata": {"key": "value"},
        "message_id": "<msg-id@example.com>",
        "attachment_names": "",
        "attachment_search_text": "",
        "raw_storage_key": None,
        "attachments": [],
        "created_at": "2024-01-01T00:00:00Z",
    })
    base.update(overrides)
    return base


def _attachment_dict(**overrides: object) -> dict:
    base = {
        "id": "att-1",
        "email_id": "email-1",
        "filename": "doc.pdf",
        "content_type": "application/pdf",
        "size_bytes": 12345,
        "content_disposition": "attachment",
        "content_id": None,
        "mime_part_index": 0,
        "text_content": "",
        "text_extraction_status": "pending",
        "storage_key": "email-1/att-1",
        "downloadable": True,
        "created_at": "2024-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _thread_dict(**overrides: object) -> dict:
    base = {
        "thread_id": "thread-1",
        "latest_email_id": "email-10",
        "from_address": "sender@example.com",
        "from_name": "Sender",
        "subject": "Thread subject",
        "received_at": "2024-01-01T00:00:00Z",
        "code": None,
        "has_attachments": False,
        "message_count": 3,
    }
    base.update(overrides)
    return base


def _with_transport(client, handler):
    """Replace the client's transport with a mock."""
    is_async = isinstance(client, AsyncMailsClient)
    cls = httpx.AsyncClient if is_async else httpx.Client
    transport = httpx.MockTransport(handler)
    client._client = cls(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
        transport=transport,
    )
    return client


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------


class TestSend:
    def test_send_constructs_correct_request(self) -> None:
        """send() should POST to /api/send with the right payload."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/send"
            assert request.headers["authorization"] == f"Bearer {TOKEN}"

            body = json.loads(request.content)
            assert body["from"] == MAILBOX
            assert body["to"] == ["user@example.com"]
            assert body["subject"] == "Test"
            assert body["text"] == "body text"
            assert body.get("html") is None

            return httpx.Response(
                200,
                json={"id": "msg-1", "provider_id": "re-123"},
            )

        client = _with_transport(_make_client(), handler)
        result = client.send("user@example.com", "Test", text="body text")
        assert isinstance(result, SendResult)
        assert result.id == "msg-1"
        assert result.provider == ""  # Worker does not return provider
        assert result.provider_id == "re-123"

    def test_send_with_multiple_recipients(self) -> None:
        """send() should accept a list of recipients."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["to"] == ["a@example.com", "b@example.com"]
            return httpx.Response(200, json={"id": "msg-2"})

        client = _with_transport(_make_client(), handler)
        result = client.send(["a@example.com", "b@example.com"], "Multi")
        assert result.id == "msg-2"

    def test_send_with_html_and_reply_to(self) -> None:
        """send() should include html and reply_to when provided."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["html"] == "<b>Hi</b>"
            assert body["reply_to"] == "reply@example.com"
            return httpx.Response(200, json={"id": "msg-3"})

        client = _with_transport(_make_client(), handler)
        client.send(
            "user@example.com",
            "HTML test",
            html="<b>Hi</b>",
            reply_to="reply@example.com",
        )

    def test_send_with_attachments(self) -> None:
        """send() should forward attachments in the payload."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert len(body["attachments"]) == 1
            assert body["attachments"][0]["filename"] == "doc.pdf"
            return httpx.Response(200, json={"id": "msg-4"})

        client = _with_transport(_make_client(), handler)
        client.send(
            "user@example.com",
            "With attachment",
            text="See attached",
            attachments=[{"filename": "doc.pdf", "content": "base64data"}],
        )

    def test_send_with_headers(self) -> None:
        """send() should forward extra headers in the payload."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["headers"] == {"X-Custom": "value"}
            return httpx.Response(200, json={"id": "msg-5"})

        client = _with_transport(_make_client(), handler)
        client.send(
            "user@example.com",
            "With headers",
            text="hi",
            headers={"X-Custom": "value"},
        )

    def test_send_hosted_uses_v1_prefix(self) -> None:
        """send() with hosted=True should POST to /v1/send."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/send"
            return httpx.Response(200, json={"id": "msg-6"})

        client = _with_transport(_make_client(hosted=True), handler)
        result = client.send("user@example.com", "Hosted", text="hi")
        assert result.id == "msg-6"


# ---------------------------------------------------------------------------
# get_inbox()
# ---------------------------------------------------------------------------


class TestGetInbox:
    def test_get_inbox_parses_response(self) -> None:
        """get_inbox() should parse the emails array from the response."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/inbox"
            assert request.url.params["to"] == MAILBOX
            assert request.url.params["limit"] == "20"
            return httpx.Response(
                200,
                json={"emails": [_email_dict(), _email_dict(id="email-2")]},
            )

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox()
        assert len(emails) == 2
        assert all(isinstance(e, Email) for e in emails)
        assert emails[0].id == "email-1"
        assert emails[1].id == "email-2"
        assert emails[0].from_address == "sender@example.com"

    def test_get_inbox_with_direction_and_query(self) -> None:
        """get_inbox() should pass direction and query params."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["direction"] == "inbound"
            assert request.url.params["query"] == "verification"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(direction="inbound", query="verification")
        assert emails == []

    def test_get_inbox_hosted_omits_to_param(self) -> None:
        """In hosted mode, get_inbox() should NOT send ?to= param."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert "to" not in request.url.params
            assert request.url.path == "/v1/inbox"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(hosted=True), handler)
        emails = client.get_inbox()
        assert emails == []

    def test_get_inbox_empty_response(self) -> None:
        """get_inbox() should handle an empty emails array."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox()
        assert emails == []

    def test_get_inbox_with_mode(self) -> None:
        """get_inbox() should pass the mode parameter."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["mode"] == "semantic"
            assert request.url.params["query"] == "meeting notes"
            return httpx.Response(200, json={"emails": [_email_dict()]})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(query="meeting notes", mode="semantic")
        assert len(emails) == 1

    def test_get_inbox_without_mode(self) -> None:
        """get_inbox() should not pass mode when not provided."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert "mode" not in request.url.params
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox()
        assert emails == []

    def test_get_inbox_mode_keyword(self) -> None:
        """get_inbox() should accept mode='keyword'."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["mode"] == "keyword"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(query="test", mode="keyword")
        assert emails == []

    def test_get_inbox_mode_hybrid(self) -> None:
        """get_inbox() should accept mode='hybrid'."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["mode"] == "hybrid"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(query="test", mode="hybrid")
        assert emails == []

    def test_get_inbox_invalid_mode_raises(self) -> None:
        """get_inbox() should raise ValueError for invalid mode."""
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid search mode"):
            client.get_inbox(query="test", mode="invalid")


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_delegates_to_get_inbox(self) -> None:
        """search() should call get_inbox with the query parameter."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["query"] == "code"
            assert request.url.params["limit"] == "10"
            return httpx.Response(
                200, json={"emails": [_email_dict(subject="Your code is 1234")]}
            )

        client = _with_transport(_make_client(), handler)
        results = client.search("code", limit=10)
        assert len(results) == 1
        assert results[0].subject == "Your code is 1234"

    def test_search_with_mode(self) -> None:
        """search() should pass the mode parameter through to get_inbox."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["query"] == "quarterly report"
            assert request.url.params["mode"] == "semantic"
            return httpx.Response(200, json={"emails": [_email_dict()]})

        client = _with_transport(_make_client(), handler)
        results = client.search("quarterly report", mode="semantic")
        assert len(results) == 1

    def test_search_invalid_mode_raises(self) -> None:
        """search() should raise ValueError for invalid mode."""
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid search mode"):
            client.search("test", mode="bad")


# ---------------------------------------------------------------------------
# get_email()
# ---------------------------------------------------------------------------


class TestGetEmail:
    def test_get_email_returns_email(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["id"] == "email-1"
            return httpx.Response(200, json=_full_email_dict())

        client = _with_transport(_make_client(), handler)
        email = client.get_email("email-1")
        assert isinstance(email, Email)
        assert email.id == "email-1"
        assert email.to_address == MAILBOX
        assert email.headers == {"X-Test": "1"}
        assert email.metadata == {"key": "value"}
        assert email.message_id == "<msg-id@example.com>"

    def test_get_email_with_attachments(self) -> None:
        """get_email() should parse nested attachments."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_full_email_dict(
                    has_attachments=True,
                    attachment_count=1,
                    attachments=[_attachment_dict()],
                ),
            )

        client = _with_transport(_make_client(), handler)
        email = client.get_email("email-1")
        assert email.has_attachments is True
        assert email.attachment_count == 1
        assert len(email.attachments) == 1
        att = email.attachments[0]
        assert isinstance(att, Attachment)
        assert att.id == "att-1"
        assert att.filename == "doc.pdf"
        assert att.downloadable is True

    def test_get_email_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(NotFoundError):
            client.get_email("nonexistent")


# ---------------------------------------------------------------------------
# wait_for_code()
# ---------------------------------------------------------------------------


class TestWaitForCode:
    def test_wait_for_code_returns_code(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["to"] == MAILBOX
            assert request.url.params["timeout"] == "30"
            return httpx.Response(
                200,
                json={
                    "id": "email-99",
                    "code": "123456",
                    "from": "noreply@service.com",
                    "subject": "Your code",
                    "received_at": "2024-01-01T00:00:00Z",
                },
            )

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code()
        assert isinstance(result, VerificationCode)
        assert result.code == "123456"
        assert result.from_address == "noreply@service.com"
        assert result.subject == "Your code"
        assert result.id == "email-99"
        assert result.received_at == "2024-01-01T00:00:00Z"

    def test_wait_for_code_returns_none_on_timeout(self) -> None:
        """wait_for_code() returns None when no code is found."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": None})

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code(timeout=5)
        assert result is None

    def test_wait_for_code_custom_timeout(self) -> None:
        """wait_for_code() should pass the timeout parameter to the API."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["timeout"] == "60"
            return httpx.Response(200, json={"code": "999999", "from": "", "subject": ""})

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code(timeout=60)
        assert result is not None
        assert result.code == "999999"

    def test_wait_for_code_with_since(self) -> None:
        """wait_for_code() should pass the since parameter to the API."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["since"] == "2024-06-01T00:00:00Z"
            return httpx.Response(
                200, json={"code": "111111", "from": "a@b.com", "subject": "Code"}
            )

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code(since="2024-06-01T00:00:00Z")
        assert result is not None
        assert result.code == "111111"

    def test_wait_for_code_hosted_omits_to(self) -> None:
        """In hosted mode, wait_for_code() should NOT send ?to= param."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert "to" not in request.url.params
            assert request.url.path == "/v1/code"
            return httpx.Response(200, json={"code": None})

        client = _with_transport(_make_client(hosted=True), handler)
        result = client.wait_for_code(timeout=5)
        assert result is None


# ---------------------------------------------------------------------------
# delete_email()
# ---------------------------------------------------------------------------


class TestDeleteEmail:
    def test_delete_email_returns_true(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.params["id"] == "email-1"
            return httpx.Response(200, json={"deleted": True})

        client = _with_transport(_make_client(), handler)
        assert client.delete_email("email-1") is True

    def test_delete_email_returns_false_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        assert client.delete_email("nonexistent") is False


# ---------------------------------------------------------------------------
# get_attachment()
# ---------------------------------------------------------------------------


class TestGetAttachment:
    def test_get_attachment_returns_bytes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/attachment"
            assert request.url.params["id"] == "att-1"
            return httpx.Response(
                200,
                content=b"%PDF-1.4 fake content",
                headers={"Content-Type": "application/pdf"},
            )

        client = _with_transport(_make_client(), handler)
        data = client.get_attachment("att-1")
        assert isinstance(data, bytes)
        assert data == b"%PDF-1.4 fake content"

    def test_get_attachment_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Attachment not found"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(NotFoundError):
            client.get_attachment("nonexistent")


# ---------------------------------------------------------------------------
# get_me()
# ---------------------------------------------------------------------------


class TestGetMe:
    def test_get_me_returns_info(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/me"
            return httpx.Response(
                200,
                json={"worker": "mails-worker", "mailbox": MAILBOX, "send": True},
            )

        client = _with_transport(_make_client(), handler)
        info = client.get_me()
        assert isinstance(info, MeInfo)
        assert info.worker == "mails-worker"
        assert info.mailbox == MAILBOX
        assert info.send is True

    def test_get_me_no_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"worker": "mails-worker", "mailbox": None, "send": False},
            )

        client = _with_transport(_make_client(), handler)
        info = client.get_me()
        assert info.mailbox is None
        assert info.send is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(AuthError):
            client.get_inbox()

    def test_403_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "Forbidden"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(AuthError):
            client.send("a@b.com", "test", text="hi")

    def test_500_raises_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Internal server error"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(ApiError) as exc_info:
            client.get_inbox()
        assert exc_info.value.status_code == 500

    def test_404_on_get_email_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(NotFoundError):
            client.get_email("missing")

    def test_non_json_error_body(self) -> None:
        """ApiError should handle non-JSON error responses gracefully."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, content=b"Bad Gateway")

        client = _with_transport(_make_client(), handler)
        with pytest.raises(ApiError) as exc_info:
            client.get_inbox()
        assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_sync_context_manager(self) -> None:
        with MailsClient(API_URL, TOKEN, MAILBOX) as client:
            assert client.mailbox == MAILBOX

    @pytest.mark.anyio
    async def test_async_context_manager(self) -> None:
        async with AsyncMailsClient(API_URL, TOKEN, MAILBOX) as client:
            assert client.mailbox == MAILBOX


# ---------------------------------------------------------------------------
# Hosted mode (v1 routes)
# ---------------------------------------------------------------------------


class TestHostedMode:
    def test_hosted_client_uses_v1_prefix(self) -> None:
        client = _make_client(hosted=True)
        assert client._prefix == "/v1"
        assert client.hosted is True

    def test_selfhosted_client_uses_api_prefix(self) -> None:
        client = _make_client(hosted=False)
        assert client._prefix == "/api"
        assert client.hosted is False

    def test_hosted_delete_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/email"
            assert request.method == "DELETE"
            return httpx.Response(200, json={"deleted": True})

        client = _with_transport(_make_client(hosted=True), handler)
        assert client.delete_email("email-1") is True

    def test_hosted_get_email_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/email"
            return httpx.Response(200, json=_full_email_dict())

        client = _with_transport(_make_client(hosted=True), handler)
        email = client.get_email("email-1")
        assert email.id == "email-1"

    def test_hosted_get_me_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/me"
            return httpx.Response(
                200,
                json={"worker": "mails-worker", "mailbox": MAILBOX, "send": True},
            )

        client = _with_transport(_make_client(hosted=True), handler)
        info = client.get_me()
        assert info.worker == "mails-worker"

    def test_hosted_get_attachment_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/attachment"
            return httpx.Response(200, content=b"data")

        client = _with_transport(_make_client(hosted=True), handler)
        data = client.get_attachment("att-1")
        assert data == b"data"


# ---------------------------------------------------------------------------
# AsyncMailsClient
# ---------------------------------------------------------------------------


class TestAsyncClient:
    @pytest.mark.anyio
    async def test_async_send(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["from"] == MAILBOX
            return httpx.Response(200, json={"id": "async-1"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.send("user@example.com", "Async test", text="hi")
        assert result.id == "async-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_inbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"emails": [_email_dict()]}
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        emails = await client.get_inbox()
        assert len(emails) == 1
        assert emails[0].id == "email-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_search(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["query"] == "test"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        results = await client.search("test")
        assert results == []
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_inbox_with_mode(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["mode"] == "semantic"
            assert request.url.params["query"] == "meeting"
            return httpx.Response(200, json={"emails": [_email_dict()]})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        emails = await client.get_inbox(query="meeting", mode="semantic")
        assert len(emails) == 1
        await client.close()

    @pytest.mark.anyio
    async def test_async_search_with_mode(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["query"] == "report"
            assert request.url.params["mode"] == "hybrid"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        results = await client.search("report", mode="hybrid")
        assert results == []
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_inbox_invalid_mode_raises(self) -> None:
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        with pytest.raises(ValueError, match="Invalid search mode"):
            await client.get_inbox(query="test", mode="invalid")
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_email(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_full_email_dict())

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        email = await client.get_email("email-1")
        assert email.id == "email-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_wait_for_code_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": None})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.wait_for_code(timeout=5)
        assert result is None
        await client.close()

    @pytest.mark.anyio
    async def test_async_delete_email(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            return httpx.Response(200, json={"deleted": True})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.delete_email("email-1") is True
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_attachment(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"attachment-data")

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        data = await client.get_attachment("att-1")
        assert data == b"attachment-data"
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_me(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"worker": "mails-worker", "mailbox": MAILBOX, "send": True},
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        info = await client.get_me()
        assert info.worker == "mails-worker"
        await client.close()

    @pytest.mark.anyio
    async def test_async_error_handling(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        with pytest.raises(AuthError):
            await client.get_inbox()
        await client.close()

    @pytest.mark.anyio
    async def test_async_hosted_mode(self) -> None:
        """Async client should support hosted=True with /v1/ prefix."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/inbox"
            assert "to" not in request.url.params
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(
            AsyncMailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler
        )
        emails = await client.get_inbox()
        assert emails == []
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_threads(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/threads"
            return httpx.Response(
                200, json={"threads": [_thread_dict()]}
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        threads = await client.get_threads()
        assert len(threads) == 1
        assert isinstance(threads[0], EmailThread)
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_thread(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/thread"
            return httpx.Response(
                200,
                json={"thread_id": "thread-1", "emails": [_email_dict()]},
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        emails = await client.get_thread("thread-1")
        assert len(emails) == 1
        assert isinstance(emails[0], Email)
        await client.close()

    @pytest.mark.anyio
    async def test_async_extract(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["email_id"] == "email-1"
            assert body["type"] == "order"
            return httpx.Response(
                200,
                json={"email_id": "email-1", "extraction": {"order_number": "ORD-123"}},
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.extract("email-1", "order")
        assert result["extraction"]["order_number"] == "ORD-123"
        await client.close()


# ---------------------------------------------------------------------------
# get_threads()
# ---------------------------------------------------------------------------


class TestGetThreads:
    def test_get_threads_returns_list(self) -> None:
        """get_threads() should return a list of EmailThread objects."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/threads"
            assert request.url.params["to"] == MAILBOX
            assert request.url.params["limit"] == "20"
            assert request.url.params["offset"] == "0"
            return httpx.Response(
                200,
                json={"threads": [_thread_dict(), _thread_dict(thread_id="thread-2")]},
            )

        client = _with_transport(_make_client(), handler)
        threads = client.get_threads()
        assert len(threads) == 2
        assert all(isinstance(t, EmailThread) for t in threads)
        assert threads[0].thread_id == "thread-1"
        assert threads[0].latest_email_id == "email-10"
        assert threads[0].message_count == 3
        assert threads[1].thread_id == "thread-2"

    def test_get_threads_with_pagination(self) -> None:
        """get_threads() should pass limit and offset."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["limit"] == "5"
            assert request.url.params["offset"] == "10"
            return httpx.Response(200, json={"threads": []})

        client = _with_transport(_make_client(), handler)
        threads = client.get_threads(limit=5, offset=10)
        assert threads == []

    def test_get_threads_empty(self) -> None:
        """get_threads() should handle empty response."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"threads": []})

        client = _with_transport(_make_client(), handler)
        threads = client.get_threads()
        assert threads == []


# ---------------------------------------------------------------------------
# get_thread()
# ---------------------------------------------------------------------------


class TestGetThread:
    def test_get_thread_returns_emails(self) -> None:
        """get_thread() should return a list of Email objects."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/thread"
            assert request.url.params["id"] == "thread-1"
            assert request.url.params["to"] == MAILBOX
            return httpx.Response(
                200,
                json={
                    "thread_id": "thread-1",
                    "emails": [
                        _email_dict(id="email-1", subject="Re: Hello"),
                        _email_dict(id="email-2", subject="Re: Hello"),
                    ],
                },
            )

        client = _with_transport(_make_client(), handler)
        emails = client.get_thread("thread-1")
        assert len(emails) == 2
        assert all(isinstance(e, Email) for e in emails)
        assert emails[0].id == "email-1"
        assert emails[1].id == "email-2"

    def test_get_thread_not_found(self) -> None:
        """get_thread() should raise NotFoundError for missing threads."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Thread not found"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(NotFoundError):
            client.get_thread("nonexistent")


# ---------------------------------------------------------------------------
# extract()
# ---------------------------------------------------------------------------


class TestExtract:
    def test_extract_returns_result(self) -> None:
        """extract() should POST and return the extraction result."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/extract"
            body = json.loads(request.content)
            assert body["email_id"] == "email-1"
            assert body["type"] == "order"
            return httpx.Response(
                200,
                json={
                    "email_id": "email-1",
                    "extraction": {"order_number": "ORD-123", "total": "$99.99"},
                },
            )

        client = _with_transport(_make_client(), handler)
        result = client.extract("email-1", "order")
        assert result["email_id"] == "email-1"
        assert result["extraction"]["order_number"] == "ORD-123"

    def test_extract_invalid_type_raises(self) -> None:
        """extract() should raise ValueError for invalid type."""
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid extraction type"):
            client.extract("email-1", "invalid")

    def test_extract_all_valid_types(self) -> None:
        """extract() should accept all valid types."""

        for extract_type in ("order", "shipping", "calendar", "receipt", "code"):
            def handler(request: httpx.Request) -> httpx.Response:
                body = json.loads(request.content)
                assert body["type"] == extract_type
                return httpx.Response(
                    200,
                    json={"email_id": "email-1", "extraction": {}},
                )

            client = _with_transport(_make_client(), handler)
            result = client.extract("email-1", extract_type)
            assert result["email_id"] == "email-1"


# ---------------------------------------------------------------------------
# get_inbox with label
# ---------------------------------------------------------------------------


class TestGetInboxWithLabel:
    def test_get_inbox_with_label(self) -> None:
        """get_inbox() should pass the label parameter."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["label"] == "newsletter"
            return httpx.Response(
                200, json={"emails": [_email_dict(subject="Weekly digest")]}
            )

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(label="newsletter")
        assert len(emails) == 1
        assert emails[0].subject == "Weekly digest"

    def test_get_inbox_without_label(self) -> None:
        """get_inbox() should not pass label when not provided."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert "label" not in request.url.params
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox()
        assert emails == []

    def test_search_with_label(self) -> None:
        """search() should pass the label parameter."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["query"] == "digest"
            assert request.url.params["label"] == "newsletter"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        results = client.search("digest", label="newsletter")
        assert results == []


# ---------------------------------------------------------------------------
# Hosted mode: threads / thread / extract
# ---------------------------------------------------------------------------


class TestHostedModeNewEndpoints:
    def test_hosted_get_threads_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/threads"
            assert "to" not in request.url.params
            return httpx.Response(200, json={"threads": [_thread_dict()]})

        client = _with_transport(_make_client(hosted=True), handler)
        threads = client.get_threads()
        assert len(threads) == 1

    def test_hosted_get_thread_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/thread"
            assert "to" not in request.url.params
            return httpx.Response(
                200,
                json={"thread_id": "thread-1", "emails": [_email_dict()]},
            )

        client = _with_transport(_make_client(hosted=True), handler)
        emails = client.get_thread("thread-1")
        assert len(emails) == 1

    def test_hosted_extract_uses_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/extract"
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={"email_id": "email-1", "extraction": {"code": "123456"}},
            )

        client = _with_transport(_make_client(hosted=True), handler)
        result = client.extract("email-1", "code")
        assert result["extraction"]["code"] == "123456"


# ---------------------------------------------------------------------------
# get_stats()
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_get_stats_returns_stats(self) -> None:
        """get_stats() should return a MailboxStats object."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/stats"
            assert request.url.params["to"] == MAILBOX
            return httpx.Response(
                200,
                json={
                    "mailbox": MAILBOX,
                    "total_emails": 42,
                    "inbound": 30,
                    "outbound": 12,
                    "emails_this_month": 5,
                },
            )

        client = _with_transport(_make_client(), handler)
        stats = client.get_stats()
        assert isinstance(stats, MailboxStats)
        assert stats.mailbox == MAILBOX
        assert stats.total_emails == 42
        assert stats.inbound == 30
        assert stats.outbound == 12
        assert stats.emails_this_month == 5

    def test_get_stats_hosted_omits_to(self) -> None:
        """In hosted mode, get_stats() should NOT send ?to= param."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/stats"
            assert "to" not in request.url.params
            return httpx.Response(
                200,
                json={
                    "mailbox": MAILBOX,
                    "total_emails": 10,
                    "inbound": 8,
                    "outbound": 2,
                    "emails_this_month": 1,
                },
            )

        client = _with_transport(_make_client(hosted=True), handler)
        stats = client.get_stats()
        assert stats.total_emails == 10

    def test_get_stats_handles_missing_fields(self) -> None:
        """get_stats() should default missing numeric fields to 0."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mailbox": MAILBOX})

        client = _with_transport(_make_client(), handler)
        stats = client.get_stats()
        assert stats.total_emails == 0
        assert stats.inbound == 0
        assert stats.outbound == 0
        assert stats.emails_this_month == 0

    def test_get_stats_auth_error(self) -> None:
        """get_stats() should raise AuthError on 401."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(AuthError):
            client.get_stats()


# ---------------------------------------------------------------------------
# Helper / parser unit tests
# ---------------------------------------------------------------------------


class TestSafeInt:
    def test_valid_int(self) -> None:
        assert _safe_int(42) == 42

    def test_valid_string(self) -> None:
        assert _safe_int("10") == 10

    def test_none_returns_default(self) -> None:
        assert _safe_int(None) == 0

    def test_none_with_custom_default(self) -> None:
        assert _safe_int(None, 99) == 99

    def test_invalid_string_returns_default(self) -> None:
        assert _safe_int("not_a_number") == 0

    def test_invalid_type_returns_default(self) -> None:
        assert _safe_int([], 5) == 5

    def test_float_value(self) -> None:
        assert _safe_int(3.7) == 3


class TestParseAttachment:
    def test_missing_id_raises_api_error(self) -> None:
        """_parse_attachment should raise ApiError when 'id' is missing."""
        with pytest.raises(ApiError, match="missing required 'id' field"):
            _parse_attachment({"filename": "test.txt"})

    def test_minimal_attachment(self) -> None:
        """_parse_attachment should handle minimal dict with just 'id'."""
        att = _parse_attachment({"id": "att-min"})
        assert att.id == "att-min"
        assert att.filename == ""
        assert att.email_id == ""
        assert att.downloadable is False


class TestParseThread:
    def test_missing_thread_id_raises(self) -> None:
        with pytest.raises(ApiError, match="missing required 'thread_id' field"):
            _parse_thread({"latest_email_id": "e-1"})

    def test_missing_latest_email_id_raises(self) -> None:
        with pytest.raises(ApiError, match="missing required 'latest_email_id' field"):
            _parse_thread({"thread_id": "t-1"})

    def test_minimal_thread(self) -> None:
        t = _parse_thread({"thread_id": "t-1", "latest_email_id": "e-1"})
        assert t.thread_id == "t-1"
        assert t.subject == ""
        assert t.message_count == 0


class TestParseEmail:
    def test_missing_id_raises(self) -> None:
        with pytest.raises(ApiError, match="missing required 'id' field"):
            _parse_email({"subject": "oops"})

    def test_minimal_email(self) -> None:
        email = _parse_email({"id": "e-min"})
        assert email.id == "e-min"
        assert email.mailbox == ""
        assert email.attachments == []
        assert email.labels == []

    def test_non_list_attachments_ignored(self) -> None:
        """If 'attachments' is not a list, it should default to []."""
        email = _parse_email({"id": "e-1", "attachments": "bad"})
        assert email.attachments == []

    def test_non_dict_headers_ignored(self) -> None:
        """If 'headers' is not a dict, it should default to {}."""
        email = _parse_email({"id": "e-1", "headers": "bad"})
        assert email.headers == {}

    def test_non_dict_metadata_ignored(self) -> None:
        """If 'metadata' is not a dict, it should default to {}."""
        email = _parse_email({"id": "e-1", "metadata": ["bad"]})
        assert email.metadata == {}

    def test_non_list_labels_ignored(self) -> None:
        """If 'labels' is not a list, it should default to []."""
        email = _parse_email({"id": "e-1", "labels": "not-a-list"})
        assert email.labels == []


class TestHandleError:
    def test_2xx_does_not_raise(self) -> None:
        """_handle_error should be a no-op for successful responses."""
        response = httpx.Response(200)
        _handle_error(response)  # should not raise

    def test_201_does_not_raise(self) -> None:
        response = httpx.Response(201)
        _handle_error(response)  # should not raise

    def test_401_raises_auth_error(self) -> None:
        response = httpx.Response(401)
        with pytest.raises(AuthError):
            _handle_error(response)

    def test_403_raises_auth_error(self) -> None:
        response = httpx.Response(403)
        with pytest.raises(AuthError):
            _handle_error(response)

    def test_404_raises_not_found(self) -> None:
        response = httpx.Response(404)
        with pytest.raises(NotFoundError):
            _handle_error(response)

    def test_500_with_json_error_message(self) -> None:
        response = httpx.Response(
            500,
            json={"error": "DB connection failed"},
        )
        with pytest.raises(ApiError, match="DB connection failed") as exc_info:
            _handle_error(response)
        assert exc_info.value.status_code == 500

    def test_500_with_non_json_body(self) -> None:
        response = httpx.Response(500, content=b"Internal Server Error")
        with pytest.raises(ApiError) as exc_info:
            _handle_error(response)
        assert exc_info.value.status_code == 500

    def test_429_raises_api_error(self) -> None:
        response = httpx.Response(429, json={"error": "Rate limited"})
        with pytest.raises(ApiError, match="Rate limited") as exc_info:
            _handle_error(response)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_auth_error_is_mails_error(self) -> None:
        assert issubclass(AuthError, MailsError)

    def test_not_found_error_is_mails_error(self) -> None:
        assert issubclass(NotFoundError, MailsError)

    def test_api_error_is_mails_error(self) -> None:
        assert issubclass(ApiError, MailsError)

    def test_api_error_has_status_code(self) -> None:
        err = ApiError("test", 503)
        assert err.status_code == 503
        assert str(err) == "test"

    def test_catch_all_mails_errors(self) -> None:
        """All SDK exceptions should be catchable via MailsError."""
        for exc_class in (AuthError, NotFoundError):
            with pytest.raises(MailsError):
                raise exc_class("test")
        with pytest.raises(MailsError):
            raise ApiError("test", 500)


# ---------------------------------------------------------------------------
# Model dataclass defaults
# ---------------------------------------------------------------------------


class TestModels:
    def test_email_defaults(self) -> None:
        email = Email(
            id="e-1",
            mailbox="box",
            from_address="a@b.com",
            from_name="A",
            subject="S",
            direction="inbound",
            status="received",
            received_at="2024-01-01",
        )
        assert email.has_attachments is False
        assert email.attachment_count == 0
        assert email.body_text == ""
        assert email.body_html == ""
        assert email.code is None
        assert email.headers == {}
        assert email.metadata == {}
        assert email.attachments == []
        assert email.labels == []
        assert email.thread_id is None

    def test_attachment_defaults(self) -> None:
        att = Attachment(id="a-1", email_id="e-1", filename="f.txt", content_type="text/plain")
        assert att.size_bytes is None
        assert att.downloadable is False
        assert att.mime_part_index == 0
        assert att.text_extraction_status == "pending"

    def test_send_result_defaults(self) -> None:
        r = SendResult(id="s-1")
        assert r.provider == ""
        assert r.provider_id is None

    def test_verification_code_defaults(self) -> None:
        vc = VerificationCode(code="123456")
        assert vc.from_address == ""
        assert vc.subject == ""
        assert vc.id is None
        assert vc.received_at is None

    def test_mailbox_stats_defaults(self) -> None:
        stats = MailboxStats(mailbox="test@test.com")
        assert stats.total_emails == 0
        assert stats.inbound == 0
        assert stats.outbound == 0
        assert stats.emails_this_month == 0

    def test_me_info_defaults(self) -> None:
        info = MeInfo(worker="w")
        assert info.mailbox is None
        assert info.send is False

    def test_email_thread_defaults(self) -> None:
        t = EmailThread(
            thread_id="t-1",
            latest_email_id="e-1",
            subject="S",
            from_address="a@b.com",
            from_name="A",
            received_at="2024-01-01",
            message_count=1,
        )
        assert t.has_attachments is False
        assert t.code is None


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_api_url_trailing_slash_stripped(self) -> None:
        """MailsClient should strip trailing slash from api_url."""
        client = MailsClient("https://example.com/", TOKEN, MAILBOX)
        assert client.api_url == "https://example.com"
        client.close()

    def test_async_api_url_trailing_slash_stripped(self) -> None:
        """AsyncMailsClient should strip trailing slash from api_url."""
        client = AsyncMailsClient("https://example.com/", TOKEN, MAILBOX)
        assert client.api_url == "https://example.com"

    def test_default_prefix_is_api(self) -> None:
        client = _make_client()
        assert client._prefix == "/api"

    def test_hosted_prefix_is_v1(self) -> None:
        client = _make_client(hosted=True)
        assert client._prefix == "/v1"

    def test_client_stores_token(self) -> None:
        client = _make_client()
        assert client.token == TOKEN

    def test_client_stores_mailbox(self) -> None:
        client = _make_client()
        assert client.mailbox == MAILBOX


# ---------------------------------------------------------------------------
# wait_for_code timeout capping
# ---------------------------------------------------------------------------


class TestWaitForCodeTimeoutCap:
    def test_timeout_capped_at_300(self) -> None:
        """wait_for_code should cap timeout at 300 seconds."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["timeout"] == "300"
            return httpx.Response(200, json={"code": None})

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code(timeout=999)
        assert result is None

    def test_timeout_below_cap_unchanged(self) -> None:
        """wait_for_code should not alter timeout below 300."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["timeout"] == "120"
            return httpx.Response(200, json={"code": None})

        client = _with_transport(_make_client(), handler)
        result = client.wait_for_code(timeout=120)
        assert result is None


# ---------------------------------------------------------------------------
# Network / connection errors
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    def test_connect_error_propagates(self) -> None:
        """Network errors from httpx should propagate as-is."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = _with_transport(_make_client(), handler)
        with pytest.raises(httpx.ConnectError):
            client.get_inbox()

    def test_timeout_error_propagates(self) -> None:
        """Timeout errors from httpx should propagate as-is."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        client = _with_transport(_make_client(), handler)
        with pytest.raises(httpx.ReadTimeout):
            client.get_email("email-1")


# ---------------------------------------------------------------------------
# Async get_stats()
# ---------------------------------------------------------------------------


class TestAsyncGetStats:
    @pytest.mark.anyio
    async def test_async_get_stats(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/stats"
            return httpx.Response(
                200,
                json={
                    "mailbox": MAILBOX,
                    "total_emails": 50,
                    "inbound": 40,
                    "outbound": 10,
                    "emails_this_month": 3,
                },
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        stats = await client.get_stats()
        assert isinstance(stats, MailboxStats)
        assert stats.total_emails == 50
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_stats_hosted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/stats"
            assert "to" not in request.url.params
            return httpx.Response(
                200,
                json={"mailbox": MAILBOX, "total_emails": 7},
            )

        client = _with_transport(
            AsyncMailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler
        )
        stats = await client.get_stats()
        assert stats.total_emails == 7
        await client.close()


# ---------------------------------------------------------------------------
# Async wait_for_code with code found
# ---------------------------------------------------------------------------


class TestAsyncWaitForCodeFound:
    @pytest.mark.anyio
    async def test_async_wait_for_code_returns_code(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "email-99",
                    "code": "654321",
                    "from": "svc@example.com",
                    "subject": "Verify",
                    "received_at": "2024-06-01T00:00:00Z",
                },
            )

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.wait_for_code()
        assert result is not None
        assert result.code == "654321"
        assert result.from_address == "svc@example.com"
        await client.close()

    @pytest.mark.anyio
    async def test_async_wait_for_code_timeout_capped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["timeout"] == "300"
            return httpx.Response(200, json={"code": None})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.wait_for_code(timeout=600)
        assert result is None
        await client.close()


# ---------------------------------------------------------------------------
# Async delete_email 404
# ---------------------------------------------------------------------------


class TestAsyncDeleteEmail404:
    @pytest.mark.anyio
    async def test_async_delete_returns_false_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.delete_email("nonexistent") is False
        await client.close()


# ---------------------------------------------------------------------------
# Async extract validation
# ---------------------------------------------------------------------------


class TestAsyncExtractValidation:
    @pytest.mark.anyio
    async def test_async_extract_invalid_type_raises(self) -> None:
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        with pytest.raises(ValueError, match="Invalid extraction type"):
            await client.extract("email-1", "invalid")
        await client.close()

    @pytest.mark.anyio
    async def test_async_extract_all_valid_types(self) -> None:
        for extract_type in ("order", "shipping", "calendar", "receipt", "code"):
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={"email_id": "email-1", "extraction": {}},
                )

            client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
            result = await client.extract("email-1", extract_type)
            assert result["email_id"] == "email-1"
            await client.close()


# ---------------------------------------------------------------------------
# Async network errors
# ---------------------------------------------------------------------------


class TestAsyncNetworkErrors:
    @pytest.mark.anyio
    async def test_async_connect_error_propagates(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        transport = httpx.MockTransport(handler)
        client._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )
        with pytest.raises(httpx.ConnectError):
            await client.get_inbox()
        await client.close()


# ---------------------------------------------------------------------------
# Emails with labels parsed correctly
# ---------------------------------------------------------------------------


class TestEmailLabels:
    def test_email_with_labels(self) -> None:
        """Emails with labels should be parsed correctly."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_full_email_dict(labels=["newsletter", "important"]),
            )

        client = _with_transport(_make_client(), handler)
        email = client.get_email("email-1")
        assert email.labels == ["newsletter", "important"]

    def test_email_thread_fields(self) -> None:
        """Emails with thread_id, in_reply_to, references should be parsed."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_full_email_dict(
                    thread_id="thread-abc",
                    in_reply_to="<prev@example.com>",
                    references="<first@example.com> <prev@example.com>",
                ),
            )

        client = _with_transport(_make_client(), handler)
        email = client.get_email("email-1")
        assert email.thread_id == "thread-abc"
        assert email.in_reply_to == "<prev@example.com>"
        assert email.references == "<first@example.com> <prev@example.com>"


# ---------------------------------------------------------------------------
# get_inbox pagination
# ---------------------------------------------------------------------------


class TestGetInboxPagination:
    def test_get_inbox_custom_limit_offset(self) -> None:
        """get_inbox() should pass custom limit and offset."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["limit"] == "5"
            assert request.url.params["offset"] == "10"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        emails = client.get_inbox(limit=5, offset=10)
        assert emails == []


# ---------------------------------------------------------------------------
# search with direction
# ---------------------------------------------------------------------------


class TestSearchWithDirection:
    def test_search_with_direction(self) -> None:
        """search() should pass direction through."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["direction"] == "outbound"
            assert request.url.params["query"] == "receipt"
            return httpx.Response(200, json={"emails": []})

        client = _with_transport(_make_client(), handler)
        results = client.search("receipt", direction="outbound")
        assert results == []


# ---------------------------------------------------------------------------
# Domain management
# ---------------------------------------------------------------------------

from mails_agent import (
    ClaimResult,
    DnsRecord,
    DnsRecords,
    Domain,
    DomainVerification,
    Mailbox,
    MailboxDeleteResult,
    WebhookRoute,
    WebhookRouteList,
)
from mails_agent.client import _parse_domain, _parse_dns_records, _parse_webhook_route


def _domain_dict(**overrides: object) -> dict:
    base = {
        "id": "dom-1",
        "domain": "example.com",
        "status": "pending",
        "mx_verified": False,
        "spf_verified": False,
        "dkim_verified": False,
        "created_at": "2024-01-01T00:00:00Z",
        "verified_at": None,
    }
    base.update(overrides)
    return base


def _domain_with_dns(**overrides: object) -> dict:
    d = _domain_dict(**overrides)
    d["dns_records"] = {
        "mx": {"type": "MX", "host": "@", "value": "mx.example.com", "priority": 10, "purpose": "Email routing"},
        "spf": {"type": "TXT", "host": "@", "value": "v=spf1 include:example.com ~all", "purpose": "SPF"},
        "dmarc": {"type": "TXT", "host": "_dmarc", "value": "v=DMARC1; p=none", "purpose": "DMARC"},
    }
    d["instructions"] = "Add the DNS records below."
    return d


class TestGetDomains:
    def test_get_domains(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains"
            return httpx.Response(200, json={"domains": [_domain_dict(), _domain_dict(id="dom-2", domain="other.com")]})

        client = _with_transport(_make_client(), handler)
        domains = client.get_domains()
        assert len(domains) == 2
        assert isinstance(domains[0], Domain)
        assert domains[0].id == "dom-1"
        assert domains[1].domain == "other.com"

    def test_get_domains_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"domains": []})

        client = _with_transport(_make_client(), handler)
        assert client.get_domains() == []


class TestAddDomain:
    def test_add_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains"
            body = json.loads(request.content)
            assert body["domain"] == "new.com"
            return httpx.Response(200, json=_domain_with_dns(id="dom-new", domain="new.com"))

        client = _with_transport(_make_client(), handler)
        domain = client.add_domain("new.com")
        assert isinstance(domain, Domain)
        assert domain.domain == "new.com"
        assert domain.dns_records is not None
        assert domain.dns_records.mx is not None
        assert domain.dns_records.mx.priority == 10
        assert domain.instructions == "Add the DNS records below."


class TestGetDomain:
    def test_get_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains/dom-1"
            return httpx.Response(200, json=_domain_with_dns())

        client = _with_transport(_make_client(), handler)
        domain = client.get_domain("dom-1")
        assert domain.id == "dom-1"
        assert domain.dns_records is not None
        assert domain.dns_records.spf is not None

    def test_get_domain_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        with pytest.raises(NotFoundError):
            client.get_domain("nope")


class TestVerifyDomain:
    def test_verify_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains/dom-1/verify"
            assert request.method == "POST"
            return httpx.Response(200, json={
                "id": "dom-1", "domain": "example.com", "status": "verified",
                "mx_verified": True, "spf_verified": True, "message": "All records verified",
            })

        client = _with_transport(_make_client(), handler)
        result = client.verify_domain("dom-1")
        assert isinstance(result, DomainVerification)
        assert result.mx_verified is True
        assert result.message == "All records verified"


class TestDeleteDomain:
    def test_delete_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains/dom-1"
            assert request.method == "DELETE"
            return httpx.Response(200, json={"ok": True})

        client = _with_transport(_make_client(), handler)
        assert client.delete_domain("dom-1") is True

    def test_delete_domain_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        assert client.delete_domain("nope") is False


# ---------------------------------------------------------------------------
# Mailbox management
# ---------------------------------------------------------------------------


class TestGetMailbox:
    def test_get_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/mailbox"
            return httpx.Response(200, json={
                "mailbox": MAILBOX, "status": "active",
                "webhook_url": "https://hook.example.com", "created_at": "2024-01-01T00:00:00Z",
            })

        client = _with_transport(_make_client(), handler)
        mb = client.get_mailbox()
        assert isinstance(mb, Mailbox)
        assert mb.status == "active"
        assert mb.webhook_url == "https://hook.example.com"

    def test_get_mailbox_no_webhook(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "mailbox": MAILBOX, "status": "active", "webhook_url": None, "created_at": "2024-01-01T00:00:00Z",
            })

        client = _with_transport(_make_client(), handler)
        mb = client.get_mailbox()
        assert mb.webhook_url is None


class TestUpdateMailbox:
    def test_update_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            body = json.loads(request.content)
            assert body["webhook_url"] == "https://new-hook.com"
            return httpx.Response(200, json={"mailbox": MAILBOX, "webhook_url": "https://new-hook.com"})

        client = _with_transport(_make_client(), handler)
        mb = client.update_mailbox(webhook_url="https://new-hook.com")
        assert mb.webhook_url == "https://new-hook.com"

    def test_update_mailbox_clear_webhook(self) -> None:
        """Passing webhook_url=None should send null to clear the webhook."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["webhook_url"] is None
            return httpx.Response(200, json={"mailbox": MAILBOX, "webhook_url": None})

        client = _with_transport(_make_client(), handler)
        mb = client.update_mailbox(webhook_url=None)
        assert mb.webhook_url is None

    def test_update_mailbox_no_args(self) -> None:
        """Omitting webhook_url should send empty body (no changes)."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert "webhook_url" not in body
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "active"})

        client = _with_transport(_make_client(), handler)
        mb = client.update_mailbox()
        assert mb.mailbox == MAILBOX


class TestDeleteMailbox:
    def test_delete_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/mailbox"
            return httpx.Response(200, json={"ok": True, "deleted": MAILBOX, "r2_blobs_deleted": 42})

        client = _with_transport(_make_client(), handler)
        result = client.delete_mailbox()
        assert isinstance(result, MailboxDeleteResult)
        assert result.ok is True
        assert result.r2_blobs_deleted == 42


class TestPauseResumeMailbox:
    def test_pause_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/mailbox/pause"
            assert request.method == "PATCH"
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "paused"})

        client = _with_transport(_make_client(), handler)
        mb = client.pause_mailbox()
        assert mb.status == "paused"

    def test_resume_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/mailbox/resume"
            assert request.method == "PATCH"
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "active"})

        client = _with_transport(_make_client(), handler)
        mb = client.resume_mailbox()
        assert mb.status == "active"


# ---------------------------------------------------------------------------
# Webhook routes
# ---------------------------------------------------------------------------


class TestWebhookRoutes:
    def test_get_webhook_routes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/mailbox/routes"
            return httpx.Response(200, json={
                "mailbox": MAILBOX,
                "routes": [
                    {"label": "code", "webhook_url": "https://hook.com/code", "created_at": "2024-01-01T00:00:00Z"},
                    {"label": "newsletter", "webhook_url": "https://hook.com/news", "created_at": "2024-01-01T00:00:00Z"},
                ],
            })

        client = _with_transport(_make_client(), handler)
        result = client.get_webhook_routes()
        assert isinstance(result, WebhookRouteList)
        assert len(result.routes) == 2
        assert result.routes[0].label == "code"

    def test_get_webhook_routes_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mailbox": MAILBOX, "routes": []})

        client = _with_transport(_make_client(), handler)
        result = client.get_webhook_routes()
        assert result.routes == []

    def test_set_webhook_route(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            body = json.loads(request.content)
            assert body["label"] == "code"
            assert body["webhook_url"] == "https://hook.com/code"
            return httpx.Response(200, json={"label": "code", "webhook_url": "https://hook.com/code"})

        client = _with_transport(_make_client(), handler)
        route = client.set_webhook_route("code", "https://hook.com/code")
        assert isinstance(route, WebhookRoute)
        assert route.label == "code"

    def test_delete_webhook_route(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.params["label"] == "newsletter"
            return httpx.Response(200, json={"ok": True, "deleted": "newsletter"})

        client = _with_transport(_make_client(), handler)
        assert client.delete_webhook_route("newsletter") is True

    def test_delete_webhook_route_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        client = _with_transport(_make_client(), handler)
        assert client.delete_webhook_route("nope") is False


# ---------------------------------------------------------------------------
# Claim mailbox + health
# ---------------------------------------------------------------------------


class TestClaimMailbox:
    def test_claim_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/claim/auto"
            body = json.loads(request.content)
            assert body["name"] == "my-agent"
            return httpx.Response(201, json={"mailbox": "my-agent@mails0.com", "api_key": "key-abc"})

        client = _with_transport(_make_client(), handler)
        result = client.claim_mailbox("my-agent")
        assert isinstance(result, ClaimResult)
        assert result.mailbox == "my-agent@mails0.com"
        assert result.api_key == "key-abc"


class TestHealth:
    def test_health_ok(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/health"
            return httpx.Response(200, json={"ok": True})

        client = _with_transport(_make_client(), handler)
        assert client.health() is True

    def test_health_down(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "down"})

        client = _with_transport(_make_client(), handler)
        assert client.health() is False

    def test_health_network_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = _with_transport(_make_client(), handler)
        assert client.health() is False


# ---------------------------------------------------------------------------
# Parser unit tests for new parsers
# ---------------------------------------------------------------------------


class TestParseDomain:
    def test_parse_domain_minimal(self) -> None:
        d = _parse_domain({"id": "d1", "domain": "x.com"})
        assert d.id == "d1"
        assert d.domain == "x.com"
        assert d.dns_records is None

    def test_parse_domain_with_dns(self) -> None:
        d = _parse_domain(_domain_with_dns())
        assert d.dns_records is not None
        assert d.dns_records.mx is not None
        assert d.dns_records.mx.type == "MX"
        assert d.dns_records.mx.priority == 10

    def test_parse_dns_records_none(self) -> None:
        assert _parse_dns_records(None) is None
        assert _parse_dns_records({}) is None


class TestParseWebhookRoute:
    def test_parse_webhook_route(self) -> None:
        r = _parse_webhook_route({"label": "code", "webhook_url": "https://x.com", "created_at": "2024-01-01"})
        assert r.label == "code"

    def test_parse_webhook_route_defaults(self) -> None:
        r = _parse_webhook_route({})
        assert r.label == ""
        assert r.webhook_url == ""


# ---------------------------------------------------------------------------
# Hosted mode for new endpoints
# ---------------------------------------------------------------------------


class TestGetEvents:
    def test_get_events_parses_sse(self) -> None:
        """get_events() should parse SSE lines into event dicts."""
        sse_body = (
            "event: email.received\n"
            'data: {"mailbox": "a@b.com", "id": "e1"}\n'
            "\n"
            "event: email.sent\n"
            'data: {"mailbox": "a@b.com", "id": "e2"}\n'
            "\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/events"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_body.encode(),
            )

        client = _with_transport(_make_client(), handler)
        events = list(client.get_events())
        assert len(events) == 2
        assert events[0]["event"] == "email.received"
        assert events[0]["data"]["id"] == "e1"
        assert events[1]["event"] == "email.sent"

    def test_get_events_default_event_type(self) -> None:
        """Events without 'event:' line should default to 'message'."""
        sse_body = 'data: {"ping": true}\n\n'

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_body.encode())

        client = _with_transport(_make_client(), handler)
        events = list(client.get_events())
        assert len(events) == 1
        assert events[0]["event"] == "message"

    def test_get_events_non_json_data(self) -> None:
        """Non-JSON data should be returned as a raw string."""
        sse_body = "data: just plain text\n\n"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_body.encode())

        client = _with_transport(_make_client(), handler)
        events = list(client.get_events())
        assert events[0]["data"] == "just plain text"

    def test_get_events_with_params(self) -> None:
        """get_events() should pass query params."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["mailbox"] == "a@b.com"
            assert request.url.params["types"] == "email.received"
            assert request.url.params["since"] == "2024-01-01T00:00:00Z"
            return httpx.Response(200, content=b"")

        client = _with_transport(_make_client(), handler)
        list(client.get_events(mailbox="a@b.com", types="email.received", since="2024-01-01T00:00:00Z"))


class TestHostedModeNewMethods:
    def test_domains_use_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/domains"
            return httpx.Response(200, json={"domains": []})

        client = _with_transport(MailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler)
        client.get_domains()

    def test_mailbox_use_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/mailbox"
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "active"})

        client = _with_transport(MailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler)
        client.get_mailbox()

    def test_claim_use_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/claim/auto"
            return httpx.Response(201, json={"mailbox": "x@mails0.com", "api_key": "k"})

        client = _with_transport(MailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler)
        client.claim_mailbox("x")

    def test_webhook_routes_use_v1(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/mailbox/routes"
            return httpx.Response(200, json={"mailbox": MAILBOX, "routes": []})

        client = _with_transport(MailsClient(API_URL, TOKEN, MAILBOX, hosted=True), handler)
        client.get_webhook_routes()


# ---------------------------------------------------------------------------
# Async tests for new endpoints
# ---------------------------------------------------------------------------


class TestAsyncDomains:
    @pytest.mark.anyio
    async def test_async_get_domains(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains"
            return httpx.Response(200, json={"domains": [_domain_dict()]})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        domains = await client.get_domains()
        assert len(domains) == 1
        assert isinstance(domains[0], Domain)
        await client.close()

    @pytest.mark.anyio
    async def test_async_add_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_domain_with_dns(domain="async.com"))

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        domain = await client.add_domain("async.com")
        assert domain.domain == "async.com"
        assert domain.dns_records is not None
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/domains/d1"
            return httpx.Response(200, json=_domain_with_dns())

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        domain = await client.get_domain("d1")
        assert domain.id == "dom-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_verify_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "d1", "domain": "x.com", "status": "verified",
                "mx_verified": True, "spf_verified": False, "message": "MX ok",
            })

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.verify_domain("d1")
        assert result.mx_verified is True
        assert result.spf_verified is False
        await client.close()

    @pytest.mark.anyio
    async def test_async_delete_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.delete_domain("d1") is True
        await client.close()


class TestAsyncMailbox:
    @pytest.mark.anyio
    async def test_async_get_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "mailbox": MAILBOX, "status": "active", "webhook_url": None, "created_at": "2024-01-01T00:00:00Z",
            })

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        mb = await client.get_mailbox()
        assert mb.status == "active"
        await client.close()

    @pytest.mark.anyio
    async def test_async_update_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mailbox": MAILBOX, "webhook_url": "https://h.com"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        mb = await client.update_mailbox(webhook_url="https://h.com")
        assert mb.webhook_url == "https://h.com"
        await client.close()

    @pytest.mark.anyio
    async def test_async_delete_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "deleted": MAILBOX, "r2_blobs_deleted": 5})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.delete_mailbox()
        assert result.ok is True
        assert result.r2_blobs_deleted == 5
        await client.close()

    @pytest.mark.anyio
    async def test_async_pause_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "paused"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        mb = await client.pause_mailbox()
        assert mb.status == "paused"
        await client.close()

    @pytest.mark.anyio
    async def test_async_resume_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mailbox": MAILBOX, "status": "active"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        mb = await client.resume_mailbox()
        assert mb.status == "active"
        await client.close()


class TestAsyncWebhookRoutes:
    @pytest.mark.anyio
    async def test_async_get_webhook_routes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "mailbox": MAILBOX, "routes": [{"label": "code", "webhook_url": "https://h.com", "created_at": "2024-01-01"}],
            })

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.get_webhook_routes()
        assert len(result.routes) == 1
        await client.close()

    @pytest.mark.anyio
    async def test_async_set_webhook_route(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"label": "code", "webhook_url": "https://h.com"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        route = await client.set_webhook_route("code", "https://h.com")
        assert route.label == "code"
        await client.close()

    @pytest.mark.anyio
    async def test_async_delete_webhook_route(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.delete_webhook_route("code") is True
        await client.close()


class TestAsyncClaimAndHealth:
    @pytest.mark.anyio
    async def test_async_claim_mailbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"mailbox": "x@mails0.com", "api_key": "key"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        result = await client.claim_mailbox("x")
        assert result.api_key == "key"
        await client.close()

    @pytest.mark.anyio
    async def test_async_health_ok(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.health() is True
        await client.close()

    @pytest.mark.anyio
    async def test_async_health_down(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "down"})

        client = _with_transport(AsyncMailsClient(API_URL, TOKEN, MAILBOX), handler)
        assert await client.health() is False
        await client.close()


# ---------------------------------------------------------------------------
# New model tests
# ---------------------------------------------------------------------------


class TestNewModels:
    def test_domain_defaults(self) -> None:
        d = Domain(id="d1", domain="x.com", status="pending")
        assert d.mx_verified is False
        assert d.dns_records is None
        assert d.instructions is None

    def test_dns_record(self) -> None:
        r = DnsRecord(type="MX", host="@", value="mx.x.com", purpose="routing", priority=10)
        assert r.priority == 10

    def test_dns_records_all_none(self) -> None:
        r = DnsRecords()
        assert r.mx is None
        assert r.spf is None
        assert r.dmarc is None

    def test_mailbox_defaults(self) -> None:
        m = Mailbox(mailbox="a@b.com")
        assert m.status == ""
        assert m.webhook_url is None

    def test_mailbox_delete_result(self) -> None:
        r = MailboxDeleteResult(ok=True, deleted="a@b.com", r2_blobs_deleted=10)
        assert r.r2_blobs_deleted == 10

    def test_webhook_route(self) -> None:
        r = WebhookRoute(label="code", webhook_url="https://x.com")
        assert r.created_at == ""

    def test_webhook_route_list(self) -> None:
        wrl = WebhookRouteList(mailbox="a@b.com", routes=[WebhookRoute(label="code", webhook_url="https://x.com")])
        assert len(wrl.routes) == 1

    def test_claim_result(self) -> None:
        c = ClaimResult(mailbox="a@b.com", api_key="key-123")
        assert c.api_key == "key-123"

    def test_domain_verification(self) -> None:
        v = DomainVerification(id="d1", domain="x.com", status="verified", mx_verified=True, spf_verified=True, message="ok")
        assert v.mx_verified is True
