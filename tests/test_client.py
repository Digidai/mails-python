"""Tests for MailsClient and AsyncMailsClient."""

from __future__ import annotations

import json

import httpx
import pytest

from mails_agent import (
    ApiError,
    AsyncMailsClient,
    AuthError,
    Email,
    MailsClient,
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


def _make_client() -> MailsClient:
    return MailsClient(API_URL, TOKEN, MAILBOX)


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
                json={"id": "msg-1", "provider": "resend", "provider_id": "re-123"},
            )

        transport = httpx.MockTransport(handler)
        client = MailsClient(API_URL, TOKEN, MAILBOX)
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = client.send("user@example.com", "Test", text="body text")
        assert isinstance(result, SendResult)
        assert result.id == "msg-1"
        assert result.provider == "resend"
        assert result.provider_id == "re-123"

    def test_send_with_multiple_recipients(self) -> None:
        """send() should accept a list of recipients."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["to"] == ["a@example.com", "b@example.com"]
            return httpx.Response(200, json={"id": "msg-2", "provider": "resend"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = client.send(["a@example.com", "b@example.com"], "Multi")
        assert result.id == "msg-2"

    def test_send_with_html_and_reply_to(self) -> None:
        """send() should include html and reply_to when provided."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["html"] == "<b>Hi</b>"
            assert body["reply_to"] == "reply@example.com"
            return httpx.Response(200, json={"id": "msg-3", "provider": "resend"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

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
            return httpx.Response(200, json={"id": "msg-4", "provider": "resend"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        client.send(
            "user@example.com",
            "With attachment",
            text="See attached",
            attachments=[{"filename": "doc.pdf", "content": "base64data"}],
        )


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

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

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

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        emails = client.get_inbox(direction="inbound", query="verification")
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

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

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
            return httpx.Response(200, json=_email_dict())

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        email = client.get_email("email-1")
        assert isinstance(email, Email)
        assert email.id == "email-1"

    def test_get_email_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

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
                    "code": "123456",
                    "from": "noreply@service.com",
                    "subject": "Your code",
                },
            )

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = client.wait_for_code()
        assert isinstance(result, VerificationCode)
        assert result.code == "123456"
        assert result.from_address == "noreply@service.com"
        assert result.subject == "Your code"

    def test_wait_for_code_returns_none_on_timeout(self) -> None:
        """wait_for_code() returns None when no code is found."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": None})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = client.wait_for_code(timeout=5)
        assert result is None

    def test_wait_for_code_custom_timeout(self) -> None:
        """wait_for_code() should pass the timeout parameter to the API."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["timeout"] == "60"
            return httpx.Response(200, json={"code": "999999", "from": "", "subject": ""})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = client.wait_for_code(timeout=60)
        assert result is not None
        assert result.code == "999999"


# ---------------------------------------------------------------------------
# delete_email()
# ---------------------------------------------------------------------------


class TestDeleteEmail:
    def test_delete_email_returns_true(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.params["id"] == "email-1"
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        assert client.delete_email("email-1") is True

    def test_delete_email_returns_false_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        assert client.delete_email("nonexistent") is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.get_inbox()

    def test_403_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "Forbidden"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.send("a@b.com", "test", text="hi")

    def test_500_raises_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Internal server error"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        with pytest.raises(ApiError) as exc_info:
            client.get_inbox()
        assert exc_info.value.status_code == 500

    def test_404_on_get_email_raises_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        transport = httpx.MockTransport(handler)
        client = _make_client()
        client._client = httpx.Client(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        with pytest.raises(NotFoundError):
            client.get_email("missing")


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
# AsyncMailsClient
# ---------------------------------------------------------------------------


class TestAsyncClient:
    @pytest.mark.anyio
    async def test_async_send(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["from"] == MAILBOX
            return httpx.Response(200, json={"id": "async-1", "provider": "resend"})

        transport = httpx.MockTransport(handler)
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        client._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = await client.send("user@example.com", "Async test", text="hi")
        assert result.id == "async-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_get_inbox(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"emails": [_email_dict()]}
            )

        transport = httpx.MockTransport(handler)
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        client._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        emails = await client.get_inbox()
        assert len(emails) == 1
        assert emails[0].id == "email-1"
        await client.close()

    @pytest.mark.anyio
    async def test_async_wait_for_code_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": None})

        transport = httpx.MockTransport(handler)
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        client._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        result = await client.wait_for_code(timeout=5)
        assert result is None
        await client.close()

    @pytest.mark.anyio
    async def test_async_error_handling(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        transport = httpx.MockTransport(handler)
        client = AsyncMailsClient(API_URL, TOKEN, MAILBOX)
        client._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {TOKEN}"},
            transport=transport,
        )

        with pytest.raises(AuthError):
            await client.get_inbox()
        await client.close()
