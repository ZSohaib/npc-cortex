---
name: npc-cortex-engine-adapter
description: Add a new game-engine adapter or native client to npc-cortex following the tested contract.
---

# npc-cortex Engine Adapter Contract

Add support for one new game engine to npc-cortex. Follow this contract so
the new engine behaves exactly like the existing ones and arrives with its
own tests. When the work is built, it is graded by
`skills/npc-client-evaluation/SKILL.md` -- any error there sends the work
back for reiteration.

## 1. Pick the integration kind

* The engine runs Python in-process (Panda3D, Godot via godot-python,
  pygame, custom loops): write an **adapter** under
  `src/npc_cortex/adapters/<engine>.py`.
* The engine cannot run Python (Unity C#, Unreal C++, Godot GDScript,
  Rust, Bevy): write a **native client** under `clients/<engine>/`
  speaking `docs/PROTOCOL.md` to `npc_cortex.server.BridgeServer`,
  plus the coordinate-mapping helpers in
  `src/npc_cortex/adapters/<engine>.py` so the mapping stays tested
  without the engine present.

Never change `src/npc_cortex/runtime.py` (or the other core modules) to
fit an engine. If the core cannot express what the engine needs, the
core contract -- not the adapter -- is the discussion to have first.

## 2. In-process adapter rules

Implement the `EngineAdapter` protocol (`adapters/__init__.py`):
`name`, `attach(runtime) -> handle`, idempotent `detach(handle)`
that never raises on an unknown handle.

* Pump exactly like the frame loop: one `runtime.pump()` per engine
  frame/tick/step. N engine steps invoke `pump()` exactly N times.
* All game-state effects (handlers, `world_state` writes, `deliver()`,
  observations, memory, engagement transitions) happen on the thread
  that called `pump()` -- never call provider, handler, gateway, or
  audit code from the adapter directly.
* After `runtime.close()`: stop pumping and never raise out of the
  engine's frame callback. `submit()`/`engage()`/`pump()` raise
  `Closed`; `cancel()`/`observations()`/`memory()` keep working.
* Positions are `(x, y)` or `(x, y, z)` tuples. Map the engine's
  vector by identity on components (`Vector3(x, y, z)` -> `(x, y, z)`);
  distances are rotation-invariant, so axis conventions need no
  conversion. Never invent a new position shape.
* Never import the engine at module top level. Duck-type engine objects
  (nodes, transforms, task managers) so the adapter imports and tests
  run without the engine installed.

## 3. Native client rules

* Mirror `src/npc_cortex/client.py` (`RemoteBridge`) method for method:
  `health`, `submit`, `pump`, `engage`, `cancel`, `observations`,
  `memory`, `audit`, `delivered`, `actions`, `register_action`, `sync`,
  `close`. Same names (in the language's casing), same field names on
  the wire, same per-frame flow: `sync` -> `submit` -> `pump` -> poll
  `actions`/`delivered`/`observations` with cursors.
* Map `409`/`Closed` and `429`/`Overloaded` to distinct error types,
  exactly like the reference client.
* Never stall the engine's frame: blocking HTTP belongs on a worker
  thread (see `clients/bevy/`), one in-flight poll at a time, skip
  (don't queue) when the previous frame is still awaiting the server.
* Coordinate mapping is the identity on components; put the mapping in
  one tested helper, and document non-obvious unit choices (e.g.
  Unreal centimetres) next to it.
* Speech comes from the bridge's provider only. Clients never ship
  scripted dialogue banks: without a configured LLM the game refuses
  to boot (or labels its test stand-in), it never plays canned lines.

## 4. Mandatory per-engine test file

Every engine ships its own test file -- never fold a new engine's tests
into another engine's file, so the community can extend engines
independently:

* Python adapters: `tests/adapters/test_<engine>.py` (runnable with
  `pytest`), using duck-typed engine fakes when the engine is absent.
* Native clients: `clients/<engine>/Tests/*` (or `tests/`) in the
  engine's own framework (Unity Test Framework, Unreal Automation
  Specs, GUT, `cargo test`), **plus** a Python protocol-conformance
  file `tests/clients/test_<engine>_protocol.py` that runs the
  engine's mapping + wire flow against a live `BridgeServer` here.

Each per-engine file must cover, at minimum:

1. Mapping round-trip: engine vector -> npc position -> engine vector.
2. Pump-per-frame: N engine steps/ticks resolve N pumps (adapters), or
   `sync`/`submit`/`pump` delivers speech end to end (clients).
3. Close contract: pumping/ticking after `close()` never raises.
4. Cancel-on-unknown-handle is inert; observations carry the exact keys
   `handle`, `actor_id`, `action`, `phase`.

## 5. Done checklist

* [ ] Adapter/client code + mapping helpers added, engine never
  imported at module top level.
* [ ] New per-engine test file(s) added per section 4, all passing.
* [ ] Full suite green: `pytest tests/` from the repo root.
* [ ] `docs/ADAPTERS.md` lists the engine with its file paths.
* [ ] No core module (`runtime.py`, `models.py`, `geometry.py`,
  `registry.py`, `gateway.py`, `audit.py`, `providers.py`) modified.
* [ ] `skills/npc-client-evaluation/SKILL.md` passes with zero errors.
