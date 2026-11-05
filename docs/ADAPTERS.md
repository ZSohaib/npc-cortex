# Engine adapters

npc_cortex runs anywhere a frame loop exists. Pick one row:

| Engine | Kind | Code | Tests |
| --- | --- | --- | --- |
| Panda3D | in-process | `adapters/panda3d.py` (`attach`) | `tests/adapters/test_panda3d_attach.py` |
| Any frame loop | in-process | `adapters/loop.py` (`FramePump`) | `tests/adapters/test_loop.py` |
| No hook available | background thread | `adapters/threaded.py` | `tests/adapters/test_threaded.py` |
| asyncio games/services | task | `adapters/asyncio_adapter.py` | `tests/adapters/test_asyncio_adapter.py` |
| Godot (Python) | in-process | `adapters/godot.py` | `tests/adapters/test_godot.py` |
| pygame/arcade/pyglet | in-process | `adapters/pygame_adapter.py` | `tests/adapters/test_pygame.py` |
| Unity (C#) | network bridge | `clients/unity/` + `adapters/unity.py` | `clients/unity/Tests/`, `tests/clients/test_unity_protocol.py`, `tests/adapters/test_unity_mapping.py` |
| Unreal (C++) | network bridge | `clients/unreal/` + `adapters/unreal.py` | `clients/unreal/NpcCortexClient.spec.cpp`, `tests/clients/test_unreal_protocol.py`, `tests/adapters/test_unreal_mapping.py` |
| Godot (GDScript) | network bridge | `clients/godot/` | `clients/godot/tests/`, `tests/clients/test_godot_protocol.py` |
| Rust (Bevy/Fyrox) | network bridge | `clients/rust/` + `adapters/rust.py` | `clients/rust/tests/`, `tests/clients/test_rust_protocol.py`, `tests/adapters/test_rust_mapping.py` |
| Bevy (ECS plugin) | network bridge | `clients/bevy/` (wraps `clients/rust/`) | `clients/bevy/tests/`, `tests/clients/test_bevy_protocol.py` |

Shared rules for every row:

* One `runtime.pump()` per engine frame; N frames pump exactly N times.
* Positions are `(x, y)` or `(x, y, z)`; engine vectors map by identity
  on components (see the per-engine mapping module).
* After `runtime.close()`, frame callbacks never raise.
* The wire protocol for network rows is `docs/PROTOCOL.md`; the Python
  reference client is `npc_cortex.client.RemoteBridge`.

Adding an engine? Read `skills/npc-cortex-engine-adapter/SKILL.md` --
it is the contract, including the mandatory per-engine test file.
