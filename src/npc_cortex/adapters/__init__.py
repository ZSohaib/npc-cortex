"""Engine adapters: bind a :class:`Runtime` to a game engine's frame loop.

Every mainstream engine pumps work once per frame; npc_cortex only needs
``runtime.pump()`` invoked regularly on a thread that may touch game
state. An adapter is therefore any object that arranges that call.

In-process adapters (the engine runs Python)::

    panda3d   attach(runtime, task_mgr)   Panda3D TaskManager (original 3.12)
    loop      attach_loop / attach_register   any engine with a per-frame hook
    threaded  attach_threaded(runtime, fps)   background pumper, engine-agnostic
    asyncio   attach_asyncio(runtime, ...)    asyncio-driven games/services
    godot     GodotAdapter                    Godot via godot-python (_process)
    pygame    PygameAdapter                   pygame / arcade / pyglet style loops

Out-of-process engines (Unity, Unreal, Godot GDScript/C#) use the network
bridge instead (:mod:`npc_cortex.server` + a native client under
``clients/``). The ``unity`` and ``unreal`` modules here only hold the
coordinate/field mapping conventions those clients implement, so the
conventions stay tested in one place.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["EngineAdapter"]


@runtime_checkable
class EngineAdapter(Protocol):
    """Contract every in-process adapter honours (see ``skills/.../SKILL.md``).

    * ``pump()`` is invoked from the engine's frame/update thread, or from
      a thread the adapter owns and documents (``threaded``/``asyncio``).
    * After ``runtime.close()``, the adapter stops pumping and never raises
      from the engine's frame callback.
    * The adapter never calls provider, handler, gateway, or audit code
      directly; all game-state effects flow through ``runtime.pump()``.
    """

    name: str

    def attach(self, runtime) -> object:
        """Start pumping ``runtime``; return an opaque handle."""
        ...  # pragma: no cover

    def detach(self, handle: object) -> None:
        """Stop pumping. Idempotent; never raises on an unknown handle."""
        ...  # pragma: no cover
