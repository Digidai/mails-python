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
    MailsClient,
    MeInfo,
    NotFoundError,
    SendResult,
    VerificationCode,
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
