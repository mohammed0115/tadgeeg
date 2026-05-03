"""Base channel adapter — all channel implementations share this contract.

Each concrete adapter takes a ``config`` dict (from the AlertRule's channels
list) plus a ``Notification`` (the rendered message) and returns a result dict
the dispatcher persists onto AlertEvent.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Notification:
    """Rendered alert payload — channel-agnostic."""
    title:    str
    body:     str
    severity: str = "medium"
    summary:  str = ""        # short, fits SMS / Slack title
    deep_link: str = ""       # tadgeeg://invoices/<id> or https://app/...
    data:     dict = field(default_factory=dict)


class BaseChannel:
    """Adapter contract — implement ``send(config, notif)``."""
    name: str = "base"

    def send(self, config: dict, notif: Notification) -> dict:
        raise NotImplementedError

    def target_label(self, config: dict) -> str:
        """Human label of the destination — stored on AlertEvent.channel_target."""
        return ""
