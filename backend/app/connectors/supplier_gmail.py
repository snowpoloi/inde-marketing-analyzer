from __future__ import annotations

import base64
import logging
import re
import time
from datetime import date, datetime, time as day_time, timedelta
from email.utils import parseaddr
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings


MAILBOX = "info@inde.gr"
READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MAX_BYTES = 10 * 1024 * 1024


class _TokenInfoLogFilter(logging.Filter):
    def filter(self, record):
        # httpx logs the full request URL at INFO; tokeninfo requires a token query.
        return "oauth2.googleapis.com/tokeninfo" not in record.getMessage()


logging.getLogger("httpx").addFilter(_TokenInfoLogFilter())


class GmailReadError(ValueError):
    pass


def decode_body(data: str) -> bytes:
    if len(data) > MAX_BYTES * 4 // 3 + 8:
        raise GmailReadError("Gmail attachment exceeds 10 MB.")
    try:
        body = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
    except Exception as exc:
        raise GmailReadError("Invalid Gmail attachment encoding.") from exc
    if len(body) > MAX_BYTES:
        raise GmailReadError("Gmail attachment exceeds 10 MB.")
    return body


class SupplierGmailReader:
    """Fixed read-only Gmail surface. OAuth refresh is the only POST request."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20, follow_redirects=False)
        self.token: str | None = None
        self.deadline = time.monotonic() + 35

    def close(self):
        self.client.close()

    def _json(self, method: str, url: str, **kwargs) -> dict:
        for attempt in range(3):
            if time.monotonic() >= self.deadline:
                raise GmailReadError("Gmail read time budget reached; retry to continue previously staged messages.")
            try:
                response = self.client.request(method, url, timeout=min(20, self.deadline - time.monotonic()), **kwargs)
            except httpx.HTTPError:
                raise GmailReadError("Gmail connection failed; retry the read later.") from None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    raise GmailReadError("Gmail is temporarily unavailable or rate limited; retry later.")
                retry = response.headers.get("Retry-After", "")
                if retry.isdigit() and int(retry) > 5:
                    raise GmailReadError("Gmail requested a cooldown; retry later.")
                time.sleep(int(retry) if retry.isdigit() else 2 ** attempt)
                continue
            if not response.is_success:
                # Never persist token-bearing URLs, request bodies or Google's error body.
                raise GmailReadError(f"Gmail authorization/read failed (HTTP {response.status_code}).")
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Expected object")
                return result
            except ValueError:
                raise GmailReadError("Gmail returned an invalid response.") from None
        raise GmailReadError("Gmail read failed.")

    def authorize(self):
        self.token = None
        if not settings.supplier_gmail_enabled or not all((settings.supplier_gmail_client_id,
                settings.supplier_gmail_client_secret, settings.supplier_gmail_refresh_token)):
            raise GmailReadError("Read-only Gmail credentials are not configured on the server.")
        token = self._json("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": settings.supplier_gmail_client_id,
            "client_secret": settings.supplier_gmail_client_secret,
            "refresh_token": settings.supplier_gmail_refresh_token,
            "grant_type": "refresh_token",
        }).get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailReadError("Gmail did not issue an access token.")
        info = self._json("GET", "https://oauth2.googleapis.com/tokeninfo", params={"access_token": token})
        scopes = set(str(info.get("scope", "")).split())
        harmless = {"openid", "email", "profile", "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/userinfo.profile"}
        if READONLY_SCOPE not in scopes or scopes - harmless - {READONLY_SCOPE}:
            raise GmailReadError("Use a dedicated token with only gmail.readonly; broader permissions are rejected.")
        if info.get("aud") != settings.supplier_gmail_client_id:
            raise GmailReadError("Gmail token belongs to a different OAuth application.")
        self.token = token
        profile = self._get("profile")
        if str(profile.get("emailAddress", "")).casefold() != MAILBOX:
            self.token = None
            raise GmailReadError("Gmail account must be info@inde.gr; no other mailbox is allowed.")

    def _get(self, path: str, **params) -> dict:
        if not self.token:
            raise GmailReadError("Gmail account has not been verified.")
        if not re.fullmatch(r"profile|messages|messages/[A-Za-z0-9_-]+(?:/attachments/[A-Za-z0-9_-]+)?", path):
            raise GmailReadError("Gmail endpoint is not allowed.")
        return self._json("GET", "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
                          params=params, headers={"Authorization": "Bearer " + self.token})

    def list_messages(self, start: date, end: date, page_token: str | None = None) -> dict:
        # Search by received date, not document date; pagination is explicit and bounded.
        athens = ZoneInfo("Europe/Athens")
        after = int(datetime.combine(start, day_time.min, athens).timestamp()) - 1
        before = int(datetime.combine(end + timedelta(days=1), day_time.min, athens).timestamp())
        query = f"after:{after} before:{before} {{from:megapap.com (from:{MAILBOX} MEGAPAP)}} -in:trash -in:spam"
        return self._get("messages", q=query, maxResults=10, **({"pageToken": page_token} if page_token else {}))

    def message(self, message_id: str) -> dict:
        return self._get("messages/" + quote(message_id, safe=""), format="full")

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        data = self._get(f"messages/{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}")
        return decode_body(data.get("data", ""))


def eligible_sender(message: dict) -> bool:
    values = [h.get("value", "") for h in message.get("payload", {}).get("headers", []) if h.get("name", "").casefold() == "from"]
    if len(values) != 1:
        return False
    address = parseaddr(values[0])[1].casefold()
    return address == MAILBOX or address.rpartition("@")[2] == "megapap.com"


def message_parts(payload: dict):
    yield payload
    for part in payload.get("parts", []):
        yield from message_parts(part)
