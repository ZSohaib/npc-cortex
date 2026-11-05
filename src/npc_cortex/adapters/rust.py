"""Rust conventions: field/coordinate mapping for the Rust client.

Rust games (Bevy, Fyrox, ...) talk to npc-cortex through the network
bridge (:mod:`npc_cortex.server`); the native client lives in
``clients/rust/``. This module pins the mapping conventions in tested
Python so every client implements the same contract:

* Positions: Bevy is y-up, but npc-cortex distances are
  rotation-invariant, so the mapping is the identity on components:
  ``[x, y, z]`` <-> ``(x, y, z)``, ``[x, y]`` <-> ``(x, y)``.
  2D games send ``(x, y)``; 3D games send ``(x, y, z)``.
* Characters: ``Player``/``NPC`` ids are entity labels (or explicit id
  strings); ``role`` maps to a marker component or bundle name.
"""

from __future__ import annotations

__all__ = ["vec_to_position", "position_to_vec3", "position_to_vec2"]


def vec_to_position(v) -> tuple:
    """``[x, y]`` / ``[x, y, z]`` (or an object with ``x``/``y``/``z``)
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
    """npc position -> ``(x, y, z)`` (missing ``z`` = 0)."""
    p = tuple(position)
    if len(p) == 2:
        return (float(p[0]), float(p[1]), 0.0)
    return (float(p[0]), float(p[1]), float(p[2]))


def position_to_vec2(position) -> tuple:
    """npc position -> ``(x, y)`` (drops ``z``)."""
    return (float(position[0]), float(position[1]))
