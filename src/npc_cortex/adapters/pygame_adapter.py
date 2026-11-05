"""pygame / arcade / pyglet style adapter: tick from the game loop.

These frameworks run plain Python loops with no registration API worth
depending on, so the adapter is a small wrapper around
:class:`~npc_cortex.adapters.loop.FramePump` with scenario-sync helpers
for sprite positions. ``pygame`` itself is never imported.
"""

from __future__ import annotations

from .loop import FramePump

__all__ = ["PygameAdapter"]


class PygameAdapter:
    """Tick from the loop; sync sprite ``(x, y)`` positions in/out.

    Usage::

        bridge = PygameAdapter(runtime)
        while running:
            for event in pygame.event.get():
                ...
            bridge.sync_sprite("p1", player_rect.center)
            bridge.tick()
            pygame.display.flip()
    """

    name = "pygame"

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.pump = FramePump(runtime)

    def tick(self) -> int:
        """Pump once; call once per frame. Returns resolved count."""
        return self.pump.tick()

    def _character(self, character_id):
        for character in list(self.runtime.scenario.players) + list(
            self.runtime.scenario.npcs
        ):
            if character.id == character_id:
                return character
        return None

    def sync_sprite(self, character_id, xy) -> bool:
        """Copy a sprite ``(x, y)`` into the scenario. ``False`` when the
        id matches no character."""
        character = self._character(character_id)
        if character is None:
            return False
        character.position = (float(xy[0]), float(xy[1]))
        return True

    def read_sprite(self, character_id):
        """Read a scenario position back as ``(x, y)`` (drops ``z``)."""
        character = self._character(character_id)
        if character is None:
            return None
        return (float(character.position[0]), float(character.position[1]))

    # -- EngineAdapter shape -----------------------------------------

    def attach(self, runtime) -> "PygameAdapter":  # noqa: D102
        return PygameAdapter(runtime)

    def detach(self, handle=None) -> None:  # noqa: D102
        target = handle if isinstance(handle, PygameAdapter) else self
        target.pump.detach()

    @property
    def ticks(self):  # noqa: D102
        return self.pump.ticks
