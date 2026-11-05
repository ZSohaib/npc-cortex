"""Action registry (spec 3.5)."""

from __future__ import annotations

from typing import Callable

__all__ = ["ActionRegistry"]


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict = {}

    def register(
        self,
        name: str,
        parameters: dict,
        min_implication: float,
        handler: Callable,
        broadcast: bool = False,
    ) -> None:
        self._actions[name] = (
            dict(parameters),
            float(min_implication),
            handler,
            bool(broadcast),
        )

    def lookup(self, name):
        try:
            return self._actions.get(name)
        except TypeError:      # unhashable name
            return None
