"""Godot in-process adapter (godot-python).

Godot games written in GDScript/C# normally use the network bridge
(:mod:`npc_cortex.server` + ``clients/godot``). Games embedding Python
via `godot-python <https://github.com/touilleMan/godot-python>`_ can use
this adapter instead: call :meth:`GodotAdapter.process` from ``_process``
and keep scenario positions in sync with node transforms.

No Godot import happens here, so the module is importable (and tested)
outside the engine; nodes are duck-typed.
"""

from __future__ import annotations

from ..models import NPC, Player
from .loop import FramePump

__all__ = ["GodotAdapter", "vec_to_position", "position_to_vec"]


def vec_to_position(v) -> tuple:
    """Godot ``Vector2``/``Vector3`` (or any ``(x, y[, z])``) -> npc position.

    Godot is y-up; npc_cortex distances are rotation-invariant, so the
    mapping is the identity on components: ``Vector3(x, y, z)`` becomes
    ``(x, y, z)`` and ``Vector2(x, y)`` becomes ``(x, y)``.
    """
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


def position_to_vec(position, vec3=None):
    """npc position -> ``(x, y)`` / ``(x, y, z)`` plain tuple for the engine.

    Pass ``vec3=True`` to force a 3-tuple (missing ``z`` becomes ``0.0``),
    ``vec3=False`` to force a 2-tuple, or leave ``None`` to preserve arity.
    """
    p = tuple(position)
    if vec3 is True and len(p) == 2:
        return (float(p[0]), float(p[1]), 0.0)
    if vec3 is False:
        return (float(p[0]), float(p[1]))
    return tuple(float(c) for c in p)


class GodotAdapter:
    """Binds a runtime to Godot's ``_process`` callback.

    Usage from a godot-python node::

        self._bridge = GodotAdapter(runtime)

        def _process(self, delta):
            self._bridge.sync_node("p1", self.get_node("Player1").position)
            self._bridge.process()
    """

    name = "godot"

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.pump = FramePump(runtime)

    # -- frame ------------------------------------------------------

    def process(self) -> int:
        """Pump once; call from ``_process``. Returns resolved count."""
        return self.pump.tick()

    # -- scenario sync ----------------------------------------------

    def _character(self, character_id):
        for character in list(self.runtime.scenario.players) + list(
            self.runtime.scenario.npcs
        ):
            if character.id == character_id:
                return character
        return None

    def sync_node(self, character_id, vec, *, online=None) -> bool:
        """Copy a node transform into the scenario. Returns ``False`` when
        ``character_id`` matches no character (never raises for that)."""
        character = self._character(character_id)
        if character is None:
            return False
        character.position = vec_to_position(vec)
        if online is not None and isinstance(character, Player):
            character.online = bool(online)
        return True

    def read_node(self, character_id, *, vec3=None):
        """Read a scenario position back for a node transform."""
        character = self._character(character_id)
        if character is None:
            return None
        return position_to_vec(character.position, vec3=vec3)

    # -- EngineAdapter shape -----------------------------------------

    def attach(self, runtime) -> "GodotAdapter":  # noqa: D102
        return GodotAdapter(runtime)

    def detach(self, handle=None) -> None:  # noqa: D102
        target = handle if isinstance(handle, GodotAdapter) else self
        target.pump.detach()

    @property
    def ticks(self):  # noqa: D102
        return self.pump.ticks
