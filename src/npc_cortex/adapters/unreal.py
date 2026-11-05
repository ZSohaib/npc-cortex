"""Unreal conventions: field/coordinate mapping for the C++ client.

Unreal (C++) talks to npc_cortex through the network bridge
(:mod:`npc_cortex.server`); the native client lives in ``clients/unreal/``
(a ``FHttpModule`` client plus a Python-API remote-control example).
This module pins the mapping conventions in tested Python:

* Positions: Unreal is z-up with centimetre units, but npc_cortex
  distances are rotation-invariant and unit-agnostic, so the mapping is
  the identity on components: ``FVector(X, Y, Z)`` <-> ``(X, Y, Z)``.
  Keep one unit scale on both sides (recommended: centimetres, matching
  Unreal) and set ``horizon`` in the same units.
* Characters: ``Player``/``NPC`` ids are actor labels (or explicit id
  strings); ``role`` maps to an actor class/tag name.
"""

from __future__ import annotations

__all__ = ["vec_to_position", "position_to_fvector", "position_to_fvector2d"]


def vec_to_position(v) -> tuple:
    """``FVector``-like ``(X, Y, Z)`` (or ``(X, Y)``) -> npc position."""
    if hasattr(v, "x") and hasattr(v, "y"):
        if hasattr(v, "z"):
            return (float(v.x), float(v.y), float(v.z))
        return (float(v.x), float(v.y))
    v = tuple(v)
    if len(v) == 2:
        return (float(v[0]), float(v[1]))
    if len(v) == 3:
        return (float(v[0]), float(v[1]), float(v[2]))
    raise ValueError("position must be 2D or 3D, got %r" % (v,))


def position_to_fvector(position) -> tuple:
    """npc position -> ``(X, Y, Z)`` for ``FVector`` (missing ``Z`` = 0)."""
    p = tuple(position)
    if len(p) == 2:
        return (float(p[0]), float(p[1]), 0.0)
    return (float(p[0]), float(p[1]), float(p[2]))


def position_to_fvector2d(position) -> tuple:
    """npc position -> ``(X, Y)`` for ``FVector2D`` (drops ``Z``)."""
    return (float(position[0]), float(position[1]))
