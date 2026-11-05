"""Unreal in-process example (Unreal Python API).

For editor tooling, cinematics scripting, or games with the Python plugin
enabled, npc_cortex can run inside Unreal directly via the generic loop
adapter -- no HTTP needed. Poll ``tick()`` from a timer or tick hook::

    import unreal
    from npc_cortex import ActionRegistry, AuditLog, Gateway, Runtime, Scenario
    from npc_cortex.adapters.loop import attach_loop

    runtime = Runtime(Scenario(), provider, ActionRegistry(), Gateway(), AuditLog())
    pump = attach_loop(runtime)

    # e.g. from a Python tick handler:
    #   sync actor transforms into runtime.scenario, submit events, then:
    resolved = pump.tick()

For packaged C++ games use the FHttpModule client (NpcCortexClient.h)
against a BridgeServer instead; the protocol is docs/PROTOCOL.md.
"""

from __future__ import annotations

try:
    import unreal  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - runs only inside Unreal
    unreal = None


def actor_location_to_position(location) -> tuple:
    """``unreal.Vector`` (cm, z-up) -> npc ``(X, Y, Z)`` position.

    Identity on components; keep horizons in centimetres to match.
    """
    return (float(location.x), float(location.y), float(location.z))
