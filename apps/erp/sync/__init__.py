"""ERP sync framework.

Directions:
  • ingestion.py        — ERP → Tadgeeg (CDC pull)
  • egress.py           — Tadgeeg → ERP (decision push-back)
  • reconciliation.py   — bidirectional diff (expected vs actual)
"""
