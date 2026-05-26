import base64
import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote


SEARCH_CONSOLE_API_BASE = "https://www.googleapis.com/webmasters/v3"
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class SearchConsoleConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._token: str | None = None

    def _site_url(self) -> str:
        site_url = str(self.config.get("site_url") or self.config.get("property_url") or "").strip()
        if not site_url:
            raise ValueError("Search Console site_url is required.")
        return site_url

    def _credentials_info(self) -> dict[str, Any]:
        raw_info = self.config.get("credentials_json") or {}
        if not raw_info and self.config.get("credentials_json_base64"):
            raw_info = base64.b64decode(str(self.config["credentials_json_base64"])).decode("utf-8")
        if not raw_info and self.config.get("credentials_file"):
            raw_info = Path(str(self.config["credentials_file"])).read_text(encoding="utf-8")
        if isinstance(raw_info, str):
            try:
                raw_info = json.loads(raw_info)
            except json.JSONDecodeError as exc:
                raise ValueError("Search Console credentials JSON must be valid JSON.") from exc
        if not isinstance(raw_info, dict):
            raw_info = {}

        client_info = raw_info.get("web") or raw_info.get("installed") or raw_info
        if not isinstance(client_info, dict):
            client_info = {}

        refresh_token = self.config.get("refresh_token") or raw_info.get("refresh_token") or client_info.get("refresh_token")
        client_id = self.config.get("client_id") or client_info.get("client_id")
        client_secret = self.config.get("client_secret") or client_info.get("client_secret")
        if not refresh_token or not client_id or not client_secret:
            raise ValueError("Search Console OAuth credentials are required.")

        return {
            "type": "authorized_user",
            "client_id": str(client_id),
            "client_secret": str(client_secret),
            "refresh_token": str(refresh_token),
            "token_uri": str(client_info.get("token_uri") or raw_info.get("token_uri") or "https://oauth2.googleapis.com/token"),
        }

    def _access_token(self) -> str:
        if self._token:
            return self._token
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError("google-auth package is not installed.") from exc

        credentials = Credentials.from_authorized_user_info(
            self._credentials_info(), scopes=[SEARCH_CONSOLE_SCOPE]
        )
        credentials.refresh(Request())
        if not credentials.token:
            raise ValueError("Search Console OAuth token refresh failed.")
        self._token = credentials.token
        return credentials.token

    def fetch_search_analytics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        import httpx

        site_url = self._site_url()
        dimensions = self.config.get("dimensions") or ["date", "query", "page", "device", "country"]
        if isinstance(dimensions, str):
            dimensions = [part.strip() for part in dimensions.split(",") if part.strip()]
        if not isinstance(dimensions, list):
            dimensions = ["date", "query", "page", "device", "country"]
        if "date" not in dimensions:
            dimensions = ["date", *dimensions]
        dimensions = [str(dimension) for dimension in dimensions if str(dimension).strip()]

        row_limit = max(1, min(int(self.config.get("row_limit", 25000)), 25000))
        max_pages = max(1, int(self.config.get("max_pages", 10)))
        timeout = float(self.config.get("timeout_seconds", 60))
        search_type = str(self.config.get("search_type") or "web")
        endpoint = f"{SEARCH_CONSOLE_API_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query"

        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=timeout) as client:
            for page_index in range(max_pages):
                body = {
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "dimensions": dimensions,
                    "rowLimit": row_limit,
                    "startRow": page_index * row_limit,
                    "searchType": search_type,
                }
                response = client.post(endpoint, headers={"Authorization": f"Bearer {self._access_token()}"}, json=body)
                if response.status_code == 401 and page_index == 0:
                    self._token = None
                    response = client.post(
                        endpoint, headers={"Authorization": f"Bearer {self._access_token()}"}, json=body
                    )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(f"Search Console API returned {response.status_code}: {response.text[:1000]}") from exc

                page_rows = response.json().get("rows") or []
                for row in page_rows:
                    keys = row.get("keys") or []
                    mapped = {
                        dimension: keys[index] if index < len(keys) else None
                        for index, dimension in enumerate(dimensions)
                    }
                    rows.append(
                        {
                            "date": mapped.get("date") or date_from.isoformat(),
                            "site_url": site_url,
                            "query": mapped.get("query"),
                            "page": mapped.get("page"),
                            "device": mapped.get("device"),
                            "country": mapped.get("country"),
                            "clicks": row.get("clicks", 0),
                            "impressions": row.get("impressions", 0),
                            "ctr": row.get("ctr", 0),
                            "position": row.get("position", 0),
                            "raw": row,
                        }
                    )
                if len(page_rows) < row_limit:
                    break
        return rows
