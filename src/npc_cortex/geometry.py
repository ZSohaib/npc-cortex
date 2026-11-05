"""Position math shared by every engine adapter.

The original contract used 2D ``(x, y)`` positions. Mainstream engines
are 3D, so positions may now be ``(x, y)`` or ``(x, y, z)``. Perception
is euclidean distance over the available components; a missing ``z``
counts as ``0.0``, so 2D behaviour is bit-for-bit identical to before
and mixed 2D/3D scenarios degrade gracefully.
"""

from __future__ import annotations

import math

__all__ = ["distance", "perceives"]


def _components(position) -> tuple:
    """Return ``(x, y, z)`` floats, defaulting a missing ``z`` to ``0.0``."""
    x, y = position[0], position[1]
    z = position[2] if len(position) > 2 else 0.0
    return (float(x), float(y), float(z))


def distance(a, b) -> float:
    """Euclidean distance between two 2D or 3D positions."""
    ax, ay, az = _components(a)
    bx, by, bz = _components(b)
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2)


def perceives(observer, actor, broadcast: bool = False) -> bool:
    """Mirror of the contract's perception rule (spec 3.6).

    Kept here so adapters and the network bridge share one implementation
    with the runtime. ``observer``/``actor`` are ``Player``/``NPC`` objects.
    """
    # Local import: models must not depend on geometry.
    from .models import Player

    if observer is actor:
        return False
    if isinstance(observer, Player) and not observer.online:
        return False
    if broadcast:
        return True
    return distance(observer.position, actor.position) <= float(observer.horizon)
