# mails-agent

Python SDK for [mails0.com](https://mails0.com) -- email capabilities for AI agents.

## Install

```bash
pip install mails-agent
```

## Quick start

```python
from mails_agent import MailsClient

client = MailsClient(
    api_url="https://mails-worker.your-domain.com",
    token="your-api-token",
    mailbox="agent@mails0.com",
)

# Send an email
result = client.send(
    to="user@example.com",
    subject="Hello from my agent",
    text="This email was sent by an AI agent.",
)
print(f"Sent: {result.id}")

# Check inbox
emails = client.get_inbox(limit=5)
for email in emails:
    print(f"{email.from_address}: {email.subject}")

# Wait for a verification code (long-polls up to 30s)
code = client.wait_for_code(timeout=30)
if code:
    print(f"Got code: {code.code}")
```

## API reference

### `MailsClient(api_url, token, mailbox, *, timeout=60.0)`

Create a synchronous client. Supports use as a context manager:

```python
with MailsClient(api_url, token, mailbox) as client:
    emails = client.get_inbox()
```

---

### `send(to, subject, *, text=None, html=None, reply_to=None, attachments=None) -> SendResult`

Send an email. `to` can be a single address or a list.

```python
result = client.send(
    to=["alice@example.com", "bob@example.com"],
    subject="Team update",
    html="<h1>Update</h1><p>Everything is on track.</p>",
    reply_to="noreply@mails0.com",
)
```

**Attachments** are passed as a list of dicts:

```python
client.send(
    to="user@example.com",
    subject="Report",
    text="See attached.",
    attachments=[{
        "filename": "report.pdf",
        "content": base64_encoded_string,
        "content_type": "application/pdf",
    }],
)
```

---

### `get_inbox(*, limit=20, offset=0, direction=None, query=None) -> list[Email]`

Fetch emails from the inbox with optional filtering.

```python
# Get latest 10 inbound emails
emails = client.get_inbox(limit=10, direction="inbound")

# Search for emails containing "invoice"
emails = client.get_inbox(query="invoice")
```

---

### `search(query, *, limit=20, direction=None) -> list[Email]`

Search emails by query string. Convenience wrapper around `get_inbox`.

```python
results = client.search("verification code", limit=5)
```

---

### `get_email(email_id) -> Email`

Fetch a single email by its ID. Raises `NotFoundError` if it does not exist.

```python
email = client.get_email("abc-123")
print(email.body_text)
```

---

### `wait_for_code(*, timeout=30) -> VerificationCode | None`

Long-poll the server for a verification code. Returns `None` if no code arrives within the timeout.

```python
code = client.wait_for_code(timeout=60)
if code:
    print(f"Code: {code.code}, From: {code.from_address}")
```

---

### `delete_email(email_id) -> bool`

Delete an email. Returns `True` if deleted, `False` if not found.

```python
deleted = client.delete_email("abc-123")
```

## Async usage

All methods are available as `async` via `AsyncMailsClient`:

```python
import asyncio
from mails_agent import AsyncMailsClient

async def main():
    async with AsyncMailsClient(
        api_url="https://mails-worker.your-domain.com",
        token="your-api-token",
        mailbox="agent@mails0.com",
    ) as client:
        # Send
        result = await client.send("user@example.com", "Hello", text="Hi!")

        # Inbox
        emails = await client.get_inbox()

        # Wait for code
        code = await client.wait_for_code(timeout=30)

asyncio.run(main())
```

## Data models

### `Email`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique email ID |
| `mailbox` | `str` | Mailbox address |
| `from_address` | `str` | Sender email |
| `from_name` | `str` | Sender display name |
| `subject` | `str` | Subject line |
| `direction` | `str` | `"inbound"` or `"outbound"` |
| `status` | `str` | `"received"`, `"sent"`, `"failed"`, `"queued"` |
| `received_at` | `str` | ISO 8601 timestamp |
| `has_attachments` | `bool` | Whether email has attachments |
| `attachment_count` | `int` | Number of attachments |
| `body_text` | `str` | Plain text body |
| `body_html` | `str` | HTML body |
| `code` | `str \| None` | Extracted verification code, if any |

### `SendResult`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Message ID |
| `provider` | `str` | Send provider used |
| `provider_id` | `str \| None` | Provider-specific ID |

### `VerificationCode`

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | The verification code |
| `from_address` | `str` | Sender of the code email |
| `subject` | `str` | Subject of the code email |

## Exceptions

| Exception | When |
|-----------|------|
| `MailsError` | Base class for all SDK errors |
| `AuthError` | 401 or 403 response |
| `NotFoundError` | 404 response |
| `ApiError` | Any other non-2xx response (has `.status_code`) |

## License

MIT
