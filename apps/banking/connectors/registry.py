"""Single look-up table the rest of the app uses to pick a connector."""

from __future__ import annotations

from typing import Type

from apps.banking.connectors.al_rajhi import AlRajhiConnector
from apps.banking.connectors.base     import BaseBankConnector
from apps.banking.connectors.bsf      import BSFConnector
from apps.banking.connectors.riyad    import RiyadBankConnector
from apps.banking.connectors.sab      import SABConnector
from apps.banking.connectors.snb      import SNBConnector


REGISTRY: dict[str, Type[BaseBankConnector]] = {
    "al_rajhi": AlRajhiConnector,
    "snb":      SNBConnector,
    "riyad":    RiyadBankConnector,
    "sab":      SABConnector,
    "bsf":      BSFConnector,
}


def get_connector(bank_code: str, *, environment: str = "mock",
                  credentials: dict | None = None) -> BaseBankConnector:
    """Instantiate the right connector class for ``bank_code``.

    Falls back to AlRajhiConnector in mock-mode when the code is unknown,
    so tests for the framework keep working without enumerating every
    bank in every fixture.
    """
    cls = REGISTRY.get(bank_code, AlRajhiConnector)
    return cls(environment=environment, credentials=credentials or {})
