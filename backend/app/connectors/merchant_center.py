from datetime import date
from typing import Any

CONTENT_SCOPE = "https://www.googleapis.com/auth/content"
MERCHANT_API_BASE = "https://merchantapi.googleapis.com"


class MerchantCenterConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._token: str | None = None

    def _access_token(self) -> str:
        if self._token:
            return self._token
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError("google-auth package is not installed.") from exc

        credentials_json = self.config.get("credentials_json") or {}
        refresh_token = self.config.get("refresh_token") or credentials_json.get("refresh_token")
        client_id = self.config.get("client_id") or credentials_json.get("client_id")
        client_secret = self.config.get("client_secret") or credentials_json.get("client_secret")
        if not refresh_token or not client_id or not client_secret:
            raise ValueError("Merchant Center OAuth credentials are required.")

        credentials = Credentials(
            token=None,
            refresh_token=str(refresh_token),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=str(client_id),
            client_secret=str(client_secret),
            scopes=[CONTENT_SCOPE],
        )
        credentials.refresh(Request())
        if not credentials.token:
            raise ValueError("Merchant Center OAuth token refresh failed.")
        self._token = credentials.token
        return self._token

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        timeout = float(self.config.get("timeout_seconds", 60))
        for attempt in range(2):
            response = httpx.request(
                method,
                f"{MERCHANT_API_BASE}{path}",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                json=json,
                timeout=timeout,
            )
            if response.status_code == 401 and attempt == 0:
                self._token = None
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                details = response.text[:1000]
                raise RuntimeError(f"Merchant API {response.status_code} for {path}: {details}") from exc
            return response.json()
        raise RuntimeError(f"Merchant API request failed for {path}.")

    def _account_id(self) -> str:
        account_id = str(self.config.get("account_id") or self.config.get("merchant_id") or "").strip()
        if account_id:
            return account_id.removeprefix("accounts/")

        response = self._request("GET", "/accounts/v1/accounts?pageSize=10")
        accounts = response.get("accounts") or []
        account_name = str(accounts[0].get("name") if accounts else "")
        if account_name.startswith("accounts/"):
            return account_name.removeprefix("accounts/")
        raise ValueError("Merchant Center account_id is required.")

    @staticmethod
    def _date_value(value: dict[str, Any] | None, fallback: date) -> str:
        if not isinstance(value, dict):
            return fallback.isoformat()
        year = int(value.get("year") or fallback.year)
        month = int(value.get("month") or fallback.month)
        day = int(value.get("day") or fallback.day)
        return date(year, month, day).isoformat()

    @staticmethod
    def _price_value(value: dict[str, Any] | None) -> str:
        if not isinstance(value, dict):
            return ""
        amount = value.get("amountMicros")
        if amount is None:
            return ""
        return str(int(amount) / 1_000_000)

    def _search_report(self, account_id: str, query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_token = ""
        while True:
            body = {"query": query, "pageSize": int(self.config.get("page_size", 1000))}
            if page_token:
                body["pageToken"] = page_token
            response = self._request("POST", f"/reports/v1/accounts/{account_id}/reports:search", json=body)
            rows.extend(response.get("results") or [])
            page_token = response.get("nextPageToken") or ""
            if not page_token:
                return rows

    def _fetch_product_performance(self, account_id: str, date_from: date, date_to: date) -> list[dict[str, Any]]:
        query = f"""
            SELECT
              date,
              offer_id,
              title,
              brand,
              category_l1,
              product_type_l1,
              clicks,
              impressions,
              click_through_rate
            FROM product_performance_view
            WHERE date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            ORDER BY clicks DESC
        """
        rows = []
        for row in self._search_report(account_id, query):
            view = row.get("productPerformanceView") or {}
            offer_id = str(view.get("offerId") or "")
            rows.append(
                {
                    "date": self._date_value(view.get("date"), date_from),
                    "item_id": offer_id,
                    "offer_id": offer_id,
                    "title": view.get("title"),
                    "brand": view.get("brand"),
                    "category": view.get("productTypeL1") or view.get("categoryL1"),
                    "google_product_category": view.get("categoryL1"),
                    "product_type": view.get("productTypeL1"),
                    "clicks": view.get("clicks"),
                    "impressions": view.get("impressions"),
                    "ctr": view.get("clickThroughRate"),
                    "raw": row,
                }
            )
        return rows

    def _fetch_product_health(self, account_id: str) -> dict[str, dict[str, Any]]:
        query = """
            SELECT
              id,
              offer_id,
              title,
              brand,
              category_l1,
              product_type_l1,
              availability,
              price,
              aggregated_reporting_context_status,
              click_potential
            FROM product_view
        """
        products: dict[str, dict[str, Any]] = {}
        for row in self._search_report(account_id, query):
            view = row.get("productView") or {}
            offer_id = str(view.get("offerId") or "")
            if not offer_id:
                continue
            products[offer_id] = {
                "item_id": offer_id,
                "offer_id": offer_id,
                "title": view.get("title"),
                "brand": view.get("brand"),
                "category": view.get("productTypeL1") or view.get("categoryL1"),
                "google_product_category": view.get("categoryL1"),
                "product_type": view.get("productTypeL1"),
                "availability": view.get("availability"),
                "price": self._price_value(view.get("price")),
                "merchant_status": view.get("aggregatedReportingContextStatus"),
                "click_potential": view.get("clickPotential"),
                "raw_product_view": row,
            }
        return products

    def _fetch_csv_export(self) -> list[dict[str, Any]]:
        csv_url = self.config.get("csv_url")
        if not csv_url:
            raise ValueError("Merchant Center OAuth credentials or csv_url are required.")

        import csv
        import io

        import httpx

        response = httpx.get(csv_url, timeout=float(self.config.get("timeout_seconds", 60)))
        response.raise_for_status()
        return list(csv.DictReader(io.StringIO(response.text)))

    def fetch_product_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not (
            self.config.get("refresh_token")
            or (isinstance(self.config.get("credentials_json"), dict) and self.config["credentials_json"].get("refresh_token"))
        ):
            return self._fetch_csv_export()

        account_id = self._account_id()
        performance_rows = self._fetch_product_performance(account_id, date_from, date_to)
        product_health = self._fetch_product_health(account_id)
        for row in performance_rows:
            health = product_health.get(str(row.get("offer_id") or ""))
            if health:
                row.update({key: value for key, value in health.items() if value not in (None, "")})
                row["raw"] = {"performance": row.get("raw"), "product_health": health.get("raw_product_view")}

        if performance_rows:
            return performance_rows

        return [{**row, "date": date_to.isoformat()} for row in product_health.values()]

