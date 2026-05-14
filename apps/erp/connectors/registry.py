"""ERP connector registry.

Maps a provider code → connector class. Adding a new provider is an
explicit code change here (deliberate — it's an integration that needs
security + commercial review, not a runtime config).
"""
from __future__ import annotations

from typing import Type

from apps.erp.connectors.base import BaseERPConnector


_REGISTRY: dict[str, str] = {
    # provider code → dotted import path of the connector class
    "sap":         "apps.erp.connectors.sap.SAPConnector",
    "oracle":      "apps.erp.connectors.oracle.OracleConnector",
    "odoo":        "apps.erp.connectors.odoo.OdooConnector",
    "dynamics":    "apps.erp.connectors.dynamics.DynamicsConnector",
    "quickbooks":  "apps.erp.connectors.quickbooks.QuickBooksConnector",
    "netsuite":    "apps.erp.connectors.netsuite.NetSuiteConnector",
}


class UnknownProviderError(RuntimeError):
    """Provider code isn't in the registry."""


def get_connector(provider: str) -> Type[BaseERPConnector]:
    """Resolve a provider code to its connector class."""
    if provider not in _REGISTRY:
        raise UnknownProviderError(
            f"ERP provider {provider!r} is not registered. "
            f"Known providers: {sorted(_REGISTRY)}"
        )
    dotted = _REGISTRY[provider]
    module_path, class_name = dotted.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def known_providers() -> list[str]:
    return sorted(_REGISTRY)
