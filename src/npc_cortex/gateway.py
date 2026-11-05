"""Speech delivery sink (spec 3.6)."""

from __future__ import annotations

__all__ = ["Gateway"]


class Gateway:
    def __init__(self) -> None:
        self.delivered: list = []

    def deliver(self, player_id: str, text: str) -> None:
        self.delivered.append((player_id, text))
