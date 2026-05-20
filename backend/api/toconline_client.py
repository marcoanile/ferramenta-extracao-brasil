"""TOConline OAuth2 REST client.

Auth flow:
  1. User visits /api/auth/toconline/start  -> redirected to TOConline login
  2. TOConline redirects back with ?code=…  -> /api/auth/toconline/callback
  3. We exchange code for access_token + refresh_token and store them.
  4. All subsequent calls use Bearer token; auto-refresh on 401.
"""
import base64
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests

import config
from storage.database import save_token, load_token

log = logging.getLogger(__name__)

API_BASE = config.TOCONLINE_API_URL.rstrip("/") + "/api"
OAUTH_URL = config.TOCONLINE_OAUTH_URL.rstrip("/")


class TOConlineClient:
    def __init__(self):
        self._token_data = None

    # ------------------------------------------------------------------ auth

    def auth_start_url(self, redirect_uri: str) -> str:
        # TOConline uses /auth (not /oauth/authorize)
        params = {
            "response_type": "code",
            "client_id": config.TOCONLINE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "commercial",
        }
        return f"{OAUTH_URL}/auth?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        creds = base64.b64encode(
            f"{config.TOCONLINE_CLIENT_ID}:{config.TOCONLINE_CLIENT_SECRET}".encode()
        ).decode()
        resp = requests.post(
            f"{OAUTH_URL}/oauth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {creds}",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": "commercial",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        expires_at = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 7890000))
        save_token(
            "toconline",
            data["access_token"],
            data.get("refresh_token", ""),
            expires_at,
            config.TOCONLINE_CLIENT_ID,
        )
        self._token_data = None
        return data

    def _refresh_access_token(self, refresh_token: str) -> str:
        creds = base64.b64encode(
            f"{config.TOCONLINE_CLIENT_ID}:{config.TOCONLINE_CLIENT_SECRET}".encode()
        ).decode()
        resp = requests.post(
            f"{OAUTH_URL}/oauth/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {creds}",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        expires_at = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 7890000))
        save_token("toconline", data["access_token"], data.get("refresh_token", refresh_token), expires_at)
        return data["access_token"]

    def _get_access_token(self) -> str | None:
        token_row = load_token("toconline")
        if not token_row:
            return None
        expires_at = token_row.get("expires_at")
        if expires_at:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if datetime.utcnow() >= expires_at - timedelta(minutes=5):
                log.info("TOConline token expired, refreshing…")
                return self._refresh_access_token(token_row["refresh_token"])
        return token_row["access_token"]

    def is_authenticated(self) -> bool:
        return self._get_access_token() is not None

    # ------------------------------------------------------------------ HTTP

    def _headers(self) -> dict:
        token = self._get_access_token()
        if not token:
            raise RuntimeError("Not authenticated with TOConline. Visit /api/auth/toconline/start first.")
        return {
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{API_BASE}/{path.lstrip('/')}"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        if resp.status_code == 401:
            token_row = load_token("toconline")
            if token_row and token_row.get("refresh_token"):
                self._refresh_access_token(token_row["refresh_token"])
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        url = f"{API_BASE}/{path.lstrip('/')}"
        resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ customers

    def list_customers(self, page: int = 1, per_page: int = 100) -> list[dict]:
        """Return all customers with pagination support."""
        all_customers = []
        while True:
            data = self._get("customers", {"page[number]": page, "page[size]": per_page})
            items = data.get("data", [])
            all_customers.extend(items)
            meta = data.get("meta", {})
            total_pages = meta.get("total_pages", 1)
            if page >= total_pages or not items:
                break
            page += 1
        return all_customers

    def get_customer(self, customer_id: str) -> dict:
        return self._get(f"customers/{customer_id}")

    # ------------------------------------------------------------------ bank accounts

    def list_bank_accounts(self) -> list[dict]:
        data = self._get("bank_accounts")
        return data.get("data", [])

    def list_company_bank_accounts(self) -> list[dict]:
        data = self._get("company_bank_accounts")
        return data.get("data", [])

    # ------------------------------------------------------------------ accounting entries (movements)

    def list_accounting_entries(self, filters: dict = None) -> list[dict]:
        """Fetch accounting journal entries for reconciliation comparison."""
        params = filters or {}
        data = self._get("accounting_entries", params)
        return data.get("data", [])

    def list_sales_documents(self, filters: dict = None) -> list[dict]:
        params = filters or {}
        data = self._get("commercial_sales_documents", params)
        return data.get("data", [])

    def list_receipts(self, filters: dict = None) -> list[dict]:
        params = filters or {}
        data = self._get("commercial_sales_receipts", params)
        return data.get("data", [])

    # ------------------------------------------------------------------ sync helpers

    def sync_customers_to_db(self) -> int:
        """Pull all TOConline customers and upsert into local DB."""
        from storage.database import upsert_client
        customers = self.list_customers()
        count = 0
        for c in customers:
            attrs = c.get("attributes", {})
            upsert_client(
                toconline_id=c["id"],
                name=attrs.get("business_name") or attrs.get("contact_name", "Unknown"),
                nif=attrs.get("tax_registration_number"),
                platform="toconline",
                meta=attrs,
            )
            count += 1
        log.info("Synced %d customers from TOConline", count)
        return count


# Singleton instance
toconline = TOConlineClient()
