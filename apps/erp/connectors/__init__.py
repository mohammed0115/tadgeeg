"""Concrete ERP connectors.

Each provider lives in its own module so vendor-specific dependencies
(SAP RFC SDK, Oracle's python-oracledb, Odoo's xmlrpc.client wrapper,
QuickBooks' intuit-oauth) are isolated and importable per-need.

Discovery is handled by ``apps.erp.connectors.registry.get_connector``.
"""
