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
client = MailsClient(api_url="https://api.mails0.com", token="...", mailbox="agent@mails0.com", hosted=True)
```

## API reference

### `MailsClient(api_url, token, mailbox, *, timeout=60.0, hosted=False)`

Create a synchronous client. Supports use as a context manager:

```python
with MailsClient(api_url, token, mailbox) as client:
    emails = client.get_inbox()
```

---

### `send(to, subject, *, from_address=None, cc=None, bcc=None, text=None, html=None, reply_to=None, in_reply_to=None, headers=None, attachments=None) -> SendResult`

Send an email. `to`, `cc`, and `bcc` each accept a single address or a list.

```python
result = client.send(
    to=["alice@example.com", "bob@example.com"],
    subject="Team update",
    html="<h1>Update</h1><p>Everything is on track.</p>",
    cc="manager@example.com",
    bcc=["audit@example.com"],
    reply_to="noreply@mails0.com",
    headers={"X-Custom-Header": "value"},
)
```

**Custom sender** — use `from_address` to set a display name (the email must match your mailbox):

```python
client.send(
    to="user@example.com",
    subject="Hello",
    text="Hi!",
    from_address="My Agent <agent@mails0.com>",
)
```

**Threading** — use `in_reply_to` with a Message-ID to create a threaded reply:

```python
result = client.send(
    to="user@example.com",
    subject="Re: Hello",
    text="Thanks!",
    in_reply_to="<original-message-id@example.com>",
)
print(f"Thread: {result.thread_id}")
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

### `get_inbox(*, limit=20, offset=0, direction=None, query=None, label=None, mode=None) -> list[Email]`

Fetch emails from the inbox with optional filtering.

```python
# Get latest 10 inbound emails
emails = client.get_inbox(limit=10, direction="inbound")

# Search for emails containing "invoice"
emails = client.get_inbox(query="invoice")

# Filter by label
emails = client.get_inbox(label="newsletter")

# Semantic search — find emails by meaning, not just keywords
emails = client.get_inbox(query="meeting notes from last week", mode="semantic")

# Hybrid search — combine keyword and semantic matching
emails = client.get_inbox(query="quarterly report", mode="hybrid")
```

The `mode` parameter controls the search strategy when `query` is provided:

| Mode | Description |
|------|-------------|
| `"keyword"` | Traditional keyword matching (default server behavior) |
| `"semantic"` | AI-powered semantic search — matches by meaning |
| `"hybrid"` | Combines keyword and semantic matching for best results |

---

### `search(query, *, limit=20, direction=None, label=None, mode=None) -> list[Email]`

Search emails by query string. Convenience wrapper around `get_inbox`.

```python
results = client.search("verification code", limit=5)

# Search within a specific label
results = client.search("digest", label="newsletter")

# Semantic search
results = client.search("emails about project deadlines", mode="semantic")
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

---

### `get_threads(*, limit=20, offset=0) -> list[EmailThread]`

Fetch conversation threads, grouped by thread ID. Each thread includes the latest email's metadata and a message count.

```python
threads = client.get_threads(limit=10)
for thread in threads:
    print(f"[{thread.message_count} msgs] {thread.subject} — {thread.from_name}")
```

---

### `get_thread(thread_id) -> list[Email]`

Fetch all emails in a conversation thread, in chronological order. Raises `NotFoundError` if the thread does not exist.

```python
emails = client.get_thread("thread-abc-123")
for email in emails:
    print(f"  {email.from_address}: {email.subject}")
```

---

### `extract(email_id, type) -> dict`

Extract structured data from an email using server-side parsing. The `type` parameter must be one of: `order`, `shipping`, `calendar`, `receipt`, `code`.

Returns a dict with `email_id` and `extraction` keys.

```python
result = client.extract("email-123", "order")
print(result["extraction"])
# {'order_number': 'ORD-456', 'total': '$99.99', ...}

result = client.extract("email-456", "shipping")
print(result["extraction"])
# {'carrier': 'UPS', 'tracking_number': '1Z999...', ...}
```

## Domain management

### `get_domains() -> list[Domain]`

List all custom domains and their verification status.

```python
domains = client.get_domains()
for d in domains:
    print(f"{d.domain}: {d.status} (MX: {d.mx_verified})")
```

### `add_domain(domain) -> Domain`

Register a new custom domain. Returns DNS records you need to configure.

```python
domain = client.add_domain("example.com")
print(domain.instructions)
for rec in [domain.dns_records.mx, domain.dns_records.spf, domain.dns_records.dmarc]:
    if rec:
        print(f"  {rec.type} {rec.host} -> {rec.value}")
```

### `get_domain(domain_id) -> Domain`

Fetch a domain by ID with its DNS records.

### `verify_domain(domain_id) -> DomainVerification`

Trigger DNS verification. Returns verification results.

```python
result = client.verify_domain("dom-123")
print(f"MX: {result.mx_verified}, SPF: {result.spf_verified}")
print(result.message)
```

### `delete_domain(domain_id) -> bool`

Delete a custom domain. Returns `True` if deleted, `False` if not found.

---

## Mailbox management

### `get_mailbox() -> Mailbox`

Fetch mailbox info and status.

```python
mb = client.get_mailbox()
print(f"Status: {mb.status}, Webhook: {mb.webhook_url}")
```

### `update_mailbox(*, webhook_url=None) -> Mailbox`

Update mailbox settings (e.g., set a webhook URL for email notifications).

```python
client.update_mailbox(webhook_url="https://my-app.com/webhook")
```

### `delete_mailbox() -> MailboxDeleteResult`

Delete the mailbox and all associated data (emails, attachments, R2 blobs).

```python
result = client.delete_mailbox()
print(f"Deleted {result.deleted}, cleaned {result.r2_blobs_deleted} blobs")
```

### `pause_mailbox() -> Mailbox`

Pause the mailbox (stops receiving emails).

### `resume_mailbox() -> Mailbox`

Resume a paused mailbox.

---

## Webhook routes

### `get_webhook_routes() -> WebhookRouteList`

List label-specific webhook routes.

```python
routes = client.get_webhook_routes()
for r in routes.routes:
    print(f"  {r.label} -> {r.webhook_url}")
```

### `set_webhook_route(label, webhook_url) -> WebhookRoute`

Create or update a webhook route for a specific label.

```python
client.set_webhook_route("code", "https://my-app.com/codes")
client.set_webhook_route("newsletter", "https://my-app.com/news")
```

### `delete_webhook_route(label) -> bool`

Delete a webhook route. Returns `True` if deleted, `False` if not found.

---

## Claim and health

### `claim_mailbox(name) -> ClaimResult`

Claim a new mailbox (headless, no web UI required). Returns the mailbox address and an API key.

```python
result = client.claim_mailbox("my-agent")
print(f"Mailbox: {result.mailbox}")
print(f"API Key: {result.api_key}")
```

### `health() -> bool`

Check if the Worker is healthy. Returns `True` if reachable, `False` on error.

---

## SSE events

### `get_events(*, mailbox=None, types=None, since=None) -> Iterator[dict]`

Stream real-time events via Server-Sent Events. Each event is a dict with `event` (type) and `data` (parsed JSON) keys.

```python
for event in client.get_events():
    print(f"[{event['event']}] {event['data']}")
```

---

## Async usage

All methods are available as `async` via `AsyncMailsClient`:

```python
import asyncio
from mails_agent import AsyncMailsClient

async def main():
    async with AsyncMailsClient(
        api_url="https://api.mails0.com",
        token="your-api-token",
        mailbox="agent@mails0.com",
        hosted=True,
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
| `thread_id` | `str \| None` | Conversation thread ID |
| `in_reply_to` | `str \| None` | In-Reply-To header value |
| `references` | `str \| None` | References header value |
| `labels` | `list[str]` | Auto-detected labels (e.g. `newsletter`, `notification`) |
| `attachments` | `list[Attachment]` | Attachment objects (detail endpoint only) |
| `attachment_names` | `str` | Comma-separated attachment filenames |
| `raw_storage_key` | `str \| None` | R2 storage key for raw message |

### `EmailThread`

| Field | Type | Description |
|-------|------|-------------|
| `thread_id` | `str` | Unique thread ID |
| `latest_email_id` | `str` | ID of the most recent email in the thread |
| `subject` | `str` | Subject line |
| `from_address` | `str` | Sender of the latest email |
| `from_name` | `str` | Sender display name |
| `received_at` | `str` | ISO 8601 timestamp of the latest email |
| `message_count` | `int` | Number of emails in the thread |
| `has_attachments` | `bool` | Whether the latest email has attachments |
| `code` | `str \| None` | Extracted verification code, if any |

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
| `thread_id` | `str \| None` | Conversation thread ID |

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

### `Domain`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique domain ID |
| `domain` | `str` | Domain name |
| `status` | `str` | Verification status |
| `mx_verified` | `bool` | MX record verified |
| `spf_verified` | `bool` | SPF record verified |
| `dkim_verified` | `bool` | DKIM record verified |
| `created_at` | `str` | ISO 8601 timestamp |
| `verified_at` | `str \| None` | When domain was verified |
| `dns_records` | `DnsRecords \| None` | Required DNS records |
| `instructions` | `str \| None` | Setup instructions |

### `DomainVerification`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Domain ID |
| `domain` | `str` | Domain name |
| `status` | `str` | Verification status |
| `mx_verified` | `bool` | MX record verified |
| `spf_verified` | `bool` | SPF record verified |
| `message` | `str` | Verification result message |

### `Mailbox`

| Field | Type | Description |
|-------|------|-------------|
| `mailbox` | `str` | Mailbox address |
| `status` | `str` | `"active"` or `"paused"` |
| `webhook_url` | `str \| None` | Webhook URL for notifications |
| `created_at` | `str` | ISO 8601 timestamp |

### `MailboxDeleteResult`

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `bool` | Whether deletion succeeded |
| `deleted` | `str` | Deleted mailbox address |
| `r2_blobs_deleted` | `int` | Number of R2 blobs cleaned up |

### `MailboxStats`

| Field | Type | Description |
|-------|------|-------------|
| `mailbox` | `str` | Mailbox address |
| `total_emails` | `int` | Total email count |
| `inbound` | `int` | Inbound email count |
| `outbound` | `int` | Outbound email count |
| `emails_this_month` | `int` | Emails received this month |
| `ingest` | `IngestStats \| None` | Ingest pipeline statistics |
| `suppression_count` | `int` | Number of suppressed addresses |
| `webhook_routes` | `int` | Number of webhook routes configured |

### `IngestStats`

| Field | Type | Description |
|-------|------|-------------|
| `pending` | `int` | Emails pending processing |
| `parsed` | `int` | Successfully parsed emails |
| `failed` | `int` | Failed email processing |

### `WebhookRoute`

| Field | Type | Description |
|-------|------|-------------|
| `label` | `str` | Email label (e.g. `"code"`, `"newsletter"`) |
| `webhook_url` | `str` | Webhook URL |
| `created_at` | `str` | ISO 8601 timestamp |

### `ClaimResult`

| Field | Type | Description |
|-------|------|-------------|
| `mailbox` | `str` | Claimed mailbox address |
| `api_key` | `str` | API key for the new mailbox |

## Exceptions

| Exception | When |
|-----------|------|
| `MailsError` | Base class for all SDK errors |
| `AuthError` | 401 or 403 response |
| `NotFoundError` | 404 response |
| `ApiError` | Any other non-2xx response (has `.status_code`) |

## Ecosystem

| Project | Description |
|---|---|
| [mails](https://github.com/Digidai/mails) | Email server (Worker) + CLI + TypeScript SDK |
| [mails-agent-mcp](https://github.com/Digidai/mails-mcp) | MCP Server for AI agents |
| [mails-agent (Python)](https://github.com/Digidai/mails-python) (this repo) | Python SDK |
| [mails-skills](https://github.com/Digidai/mails-skills) | Skill files for AI agents |

## License

MIT
