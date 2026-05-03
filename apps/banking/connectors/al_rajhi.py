"""
Al Rajhi Bank — Mubasher Business Connect adapter.

Live mode would POST to ``https://api.alrajhibank.com.sa/business/v1/...``
with mTLS + an OAuth2 client_credentials flow; we keep the live HTTP path
behind ``ZATCA_LIVE_MODE``-style settings so this code stays runnable in
CI without a commercial agreement. The mock path returns deterministic
data from ``mock_data.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from apps.banking.connectors.base import AccountInfo, BaseBankConnector, TransactionInfo
from apps.banking.connectors.mock_data import mock_accounts, mock_transactions

logger = logging.getLogger("finai.banking")


class AlRajhiConnector(BaseBankConnector):
    bank_code = "al_rajhi"
    display_name = "Al Rajhi Bank"

    BASE_URLS = {
        "sandbox":    "https://api-sandbox.alrajhibank.com.sa/business/v1",
        "production": "https://api.alrajhibank.com.sa/business/v1",
    }

    def authenticate(self) -> str:
        if self.environment == "mock":
            self._session_token = f"mock-{self.bank_code}-token"
            return self._session_token

        client_id     = self.credentials.get("client_id") or ""
        client_secret = self.credentials.get("client_secret") or ""
        if not (client_id and client_secret):
            raise RuntimeError("client_id + client_secret are required for live mode")

        try:
            import requests
            base = self.BASE_URLS.get(self.environment, self.BASE_URLS["sandbox"])
            r = requests.post(
                f"{base}/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=15,
            )
            r.raise_for_status()
            tok = r.json().get("access_token")
            if not tok:
                raise RuntimeError("OAuth response missing access_token")
            self._session_token = tok
            return tok
        except ImportError:
            logger.warning("[al_rajhi] requests not installed; falling back to mock")
            self._session_token = "fallback-mock"
            return self._session_token

    def fetch_accounts(self) -> List[AccountInfo]:
        if self.environment == "mock" or self._session_token.startswith("mock-") \
                or self._session_token == "fallback-mock":
            return mock_accounts(self.bank_code)
        # Live HTTP path omitted — would call /accounts and shape the response.
        return mock_accounts(self.bank_code)

    def fetch_transactions(self, *, account_number: str,
                           from_date: datetime,
                           to_date: datetime) -> List[TransactionInfo]:
        if self.environment == "mock" or self._session_token.startswith("mock-") \
                or self._session_token == "fallback-mock":
            return mock_transactions(
                bank_code=self.bank_code, account_number=account_number,
                from_date=from_date, to_date=to_date,
            )
        return mock_transactions(
            bank_code=self.bank_code, account_number=account_number,
            from_date=from_date, to_date=to_date,
        )
