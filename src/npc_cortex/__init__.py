"""npc_cortex: drive game-engine NPCs from an LLM without stalling the frame loop.

Public API (unchanged from the original contract)::

    Player, NPC, Scenario, Event, Overloaded, Closed,
    ActionRegistry, Gateway, AuditLog, HttpProvider, Runtime, attach

``attach(runtime, task_mgr)`` keeps its original Panda3D meaning. Every
other engine integrates through :mod:`npc_cortex.adapters` (in-process)
or :mod:`npc_cortex.server` (network bridge for Unity, Unreal, Godot).
"""

from __future__ import annotations

from .audit import AuditLog
from .gateway import Gateway
from .models import NPC, Closed, Event, Overloaded, Player, Scenario
from .places import Place, WorldMap
from .providers import HttpProvider
from .registry import ActionRegistry
from .runtime import Runtime

__version__ = "0.1.0"

__all__ = [
    "Player",
    "NPC",
    "Scenario",
    "Event",
    "Overloaded",
    "Closed",
    "ActionRegistry",
    "Gateway",
    "AuditLog",
    "HttpProvider",
    "Runtime",
    "Place",
    "WorldMap",
    "attach",
]


def attach(runtime, task_mgr) -> None:
    """Attach ``runtime.pump()`` to a Panda3D task manager (spec 3.12).

    Lazily imported so ``import npc_cortex`` never requires Panda3D.
    """
    from .adapters.panda3d import attach as _attach

    _attach(runtime, task_mgr)
