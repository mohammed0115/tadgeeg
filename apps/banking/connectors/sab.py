"""Saudi Awwal Bank (SAB) — Open Banking pilot adapter."""

from __future__ import annotations

from datetime import datetime
from typing import List

from apps.banking.connectors.base import AccountInfo, BaseBankConnector, TransactionInfo
from apps.banking.connectors.mock_data import mock_accounts, mock_transactions


class SABConnector(BaseBankConnector):
    bank_code = "sab"
    display_name = "Saudi Awwal Bank"

    def authenticate(self) -> str:
        # SAB plays in the SAMA Open Banking pilot — auth is OAuth2 +
        # a per-customer consent token. Live mode would walk the FAPI flow.
        self._session_token = f"mock-{self.bank_code}"
        return self._session_token

    def fetch_accounts(self) -> List[AccountInfo]:
        return mock_accounts(self.bank_code)

    def fetch_transactions(self, *, account_number: str,
                           from_date: datetime,
                           to_date: datetime) -> List[TransactionInfo]:
        return mock_transactions(
            bank_code=self.bank_code, account_number=account_number,
            from_date=from_date, to_date=to_date,
        )
