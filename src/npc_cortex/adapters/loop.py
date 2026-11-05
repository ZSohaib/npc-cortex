"""Generic frame-loop adapter: fits any engine with a per-frame hook.

Two integration styles:

* ``attach_loop(runtime)`` returns a :class:`FramePump` whose ``tick()``
  the engine calls once per frame (Godot ``_process``, pygame loop,
  custom ``while`` loops, ...).
* ``attach_register(runtime, register)`` wires into engines that accept
  a callback, e.g. ``attach_register(rt, engine.on_update.add)``.
"""

from __future__ import annotations

from ..models import Closed

__all__ = ["FramePump", "attach_loop", "attach_register"]


class FramePump:
    """Owns the per-frame ``runtime.pump()`` call for one runtime."""

    name = "loop"

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.ticks = 0
        self.resolved = 0
        self._detached = False

    def tick(self) -> int:
        """Pump once. Safe to call after ``close()`` or ``detach()``."""
        if self._detached:
            return 0
        try:
            n = self.runtime.pump()
        except Closed:
            self._detached = True
            return 0
        self.ticks += 1
        self.resolved += n
        return n

    def detach(self) -> None:
        """Stop pumping. Idempotent."""
        self._detached = True

    # EngineAdapter-shaped aliases ------------------------------------

    def attach(self, runtime) -> "FramePump":  # noqa: D102
        return attach_loop(runtime)

    def __call__(self) -> int:
        return self.tick()


def attach_loop(runtime) -> FramePump:
    """Return a :class:`FramePump` the engine ticks once per frame."""
    return FramePump(runtime)


class _RegisteredPump(FramePump):
    def __init__(self, runtime, unregister) -> None:
        super().__init__(runtime)
        self._unregister = unregister

    def detach(self) -> None:
        super().detach()
        unregister, self._unregister = self._unregister, None
        if unregister is not None:
            try:
                unregister(self.tick)
            except Exception:
                pass


def attach_register(runtime, register, unregister=None) -> FramePump:
    """Register ``pump.tick`` with an engine callback list.

    ``register`` is called with the tick callable; ``unregister``, when
    given, is called with it on ``detach()``. Returns the pump, which also
    serves as the detach handle.
    """
    pump = _RegisteredPump(runtime, unregister)
    register(pump.tick)
    return pump
