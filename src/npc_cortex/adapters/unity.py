"""Unity conventions: field/coordinate mapping for the C# client.

Unity (C#) talks to npc_cortex through the network bridge
(:mod:`npc_cortex.server`, `` POST /v1/...``); the native client lives in
``clients/unity/``. This module pins the mapping conventions in tested
Python so every client implements the same contract:

* Positions: Unity is y-up, but npc_cortex distances are
  rotation-invariant, so the mapping is the identity on components:
  ``Vector3(x, y, z)`` <-> ``(x, y, z)``, ``Vector2(x, y)`` <-> ``(x, y)``.
  2D games send ``(x, y)``; 3D games send ``(x, y, z)``.
* Characters: ``Player``/``NPC`` ids are Unity ``GameObject`` names (or
  explicit id strings); ``role`` maps to a tag/prefab name.
"""

from __future__ import annotations

__all__ = ["vec_to_position", "position_to_vec3", "position_to_vec2"]


def vec_to_position(v) -> tuple:
    """``(x, y)`` / ``(x, y, z)`` (or an object with ``x``/``y``/``z``)
    -> npc position tuple."""
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


def position_to_vec3(position) -> tuple:
    """npc position -> ``(x, y, z)`` for ``Vector3`` (missing ``z`` = 0)."""
    p = tuple(position)
    if len(p) == 2:
        return (float(p[0]), float(p[1]), 0.0)
    return (float(p[0]), float(p[1]), float(p[2]))


def position_to_vec2(position) -> tuple:
    """npc position -> ``(x, y)`` for ``Vector2`` (drops ``z``)."""
    return (float(position[0]), float(position[1]))
