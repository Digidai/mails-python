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

## Self-hosted vs. hosted mode

The SDK supports two routing modes that match the Worker API:

- **Self-hosted** (`/api/*` routes, default): The `?to=` query parameter is sent for mailbox filtering. Use this when running your own Worker.
- **Hosted** (`/v1/*` routes): The mailbox is bound to the API token, so `?to=` is not needed. Use this for the hosted mails0.com service.

```python
# Self-hosted (default)
client = MailsClient(api_url="https://your-worker.com", token="...", mailbox="agent@mails0.com")

# Hosted
client = MailsClient(api_url="https://mails-worker.genedai.workers.dev", token="...", mailbox="agent@mails0.com", hosted=True)
```

## API reference

### `MailsClient(api_url, token, mailbox, *, timeout=60.0, hosted=False)`

Create a synchronous client. Supports use as a context manager:

```python
with MailsClient(api_url, token, mailbox) as client:
    emails = client.get_inbox()
```

---

### `send(to, subject, *, text=None, html=None, reply_to=None, headers=None, attachments=None) -> SendResult`

Send an email. `to` can be a single address or a list.

```python
result = client.send(
    to=["alice@example.com", "bob@example.com"],
    subject="Team update",
    html="<h1>Update</h1><p>Everything is on track.</p>",
    reply_to="noreply@mails0.com",
    headers={"X-Custom-Header": "value"},
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

Fetch a single email by its ID (includes full body, headers, metadata, and attachments). Raises `NotFoundError` if it does not exist.

```python
email = client.get_email("abc-123")
print(email.body_text)
for att in email.attachments:
    print(f"  Attachment: {att.filename} ({att.content_type})")
```

---

### `wait_for_code(*, timeout=30, since=None) -> VerificationCode | None`

Long-poll the server for a verification code. Returns `None` if no code arrives within the timeout.

```python
code = client.wait_for_code(timeout=60)
if code:
    print(f"Code: {code.code}, From: {code.from_address}")

# Only consider codes received after a specific time
code = client.wait_for_code(timeout=30, since="2024-06-01T00:00:00Z")
```

---

### `delete_email(email_id) -> bool`

Delete an email. Returns `True` if deleted, `False` if not found.

```python
deleted = client.delete_email("abc-123")
```

---

### `get_attachment(attachment_id) -> bytes`

Download an attachment by its ID. Returns raw bytes.

```python
data = client.get_attachment("att-456")
with open("downloaded.pdf", "wb") as f:
    f.write(data)
```

---

### `get_me() -> MeInfo`

Fetch information about the current authentication context.

```python
info = client.get_me()
print(f"Worker: {info.worker}, Mailbox: {info.mailbox}, Send: {info.send}")
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

        # Download attachment
        data = await client.get_attachment("att-id")

        # Check auth context
        info = await client.get_me()

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
| `to_address` | `str` | Recipient address |
| `subject` | `str` | Subject line |
| `direction` | `str` | `"inbound"` or `"outbound"` |
| `status` | `str` | `"received"`, `"sent"`, `"failed"`, `"queued"` |
| `received_at` | `str` | ISO 8601 timestamp |
| `created_at` | `str` | ISO 8601 timestamp |
| `has_attachments` | `bool` | Whether email has attachments |
| `attachment_count` | `int` | Number of attachments |
| `body_text` | `str` | Plain text body |
| `body_html` | `str` | HTML body |
| `code` | `str \| None` | Extracted verification code, if any |
| `headers` | `dict` | Email headers |
| `metadata` | `dict` | Extra metadata |
| `message_id` | `str \| None` | SMTP Message-ID |
| `attachments` | `list[Attachment]` | Attachment objects (detail endpoint only) |
| `attachment_names` | `str` | Comma-separated attachment filenames |
| `raw_storage_key` | `str \| None` | R2 storage key for raw message |

### `Attachment`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique attachment ID |
| `email_id` | `str` | Parent email ID |
| `filename` | `str` | Original filename |
| `content_type` | `str` | MIME type |
| `size_bytes` | `int \| None` | Size in bytes |
| `content_disposition` | `str \| None` | Content-Disposition header |
| `content_id` | `str \| None` | Content-ID (for inline images) |
| `mime_part_index` | `int` | MIME part index |
| `text_content` | `str` | Extracted text content |
| `text_extraction_status` | `str` | `"pending"`, `"done"`, `"unsupported"`, `"failed"`, `"too_large"` |
| `storage_key` | `str \| None` | R2 storage key |
| `downloadable` | `bool` | Whether binary content is available for download |
| `created_at` | `str` | ISO 8601 timestamp |

### `SendResult`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Message ID |
| `provider` | `str` | Send provider used (may be empty) |
| `provider_id` | `str \| None` | Provider-specific ID (e.g. Resend ID) |

### `VerificationCode`

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | The verification code |
| `from_address` | `str` | Sender of the code email |
| `subject` | `str` | Subject of the code email |
| `id` | `str \| None` | Email ID containing the code |
| `received_at` | `str \| None` | When the code email was received |

### `MeInfo`

| Field | Type | Description |
|-------|------|-------------|
| `worker` | `str` | Worker name |
| `mailbox` | `str \| None` | Bound mailbox address (if authenticated) |
| `send` | `bool` | Whether sending is available |

## Exceptions

| Exception | When |
|-----------|------|
| `MailsError` | Base class for all SDK errors |
| `AuthError` | 401 or 403 response |
| `NotFoundError` | 404 response |
| `ApiError` | Any other non-2xx response (has `.status_code`) |

## License

MIT
