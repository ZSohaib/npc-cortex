"""Core data model for npc_cortex.

Unchanged from the original Panda3D-only contract, except that
``Player.position`` and ``NPC.position`` now accept either a 2D ``(x, y)``
or a 3D ``(x, y, z)`` tuple so 3D engines (Unity, Unreal, Godot 3D)
can use world positions directly. Distance math lives in
:mod:`npc_cortex.geometry` and treats a missing ``z`` as ``0.0``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Player",
    "NPC",
    "Scenario",
    "Event",
    "Overloaded",
    "Closed",
]


class Overloaded(Exception):
    """submit() past `capacity` unresolved events."""


class Closed(Exception):
    """submit(), engage() or pump() after close()."""


@dataclass
class Player:
    id: str
    role: str
    position: tuple
    horizon: float
    online: bool = True


@dataclass
class NPC:
    id: str
    position: tuple
    horizon: float
    implication: float = 1.0


@dataclass
class Scenario:
    players: list = field(default_factory=list)
    npcs: list = field(default_factory=list)
    world_state: dict = field(default_factory=dict)
    places: list = field(default_factory=list)  # Place objects; see places.py


@dataclass
class Event:
    kind: str
    npc_id: str
    speaker_id: "str | None" = None
    text: "str | None" = None
