# NPC Cortex

LLM-driven NPCs for any game engine — without stalling the frame loop.

NPC Cortex is a runtime, a cast generator, and a set of engine
integrations that together give games believable agentic NPCs: the
runtime plans what each NPC says and does through a language model,
then applies the results on the engine's own timeline. Provider calls
run on background threads with timeouts and retries, while speech,
actions, observations, and memory all land inside a single `pump()`
your frame loop (or a network poll) invokes. Perception, implication
gating, engagements, environment awareness, mutual NPC knowledge, and
a full audit trail come built in.

> Renamed from `npc-bridge` to `npc-cortex`. The old
> `NPC_LLM_API_KEY` variable is still honoured as a fallback; new
> setups should use `NPC_CORTEX_API_KEY`.

## What this repo is

Three layers, each usable alone:

1. **Runtime** (`src/npc_cortex/`) — engine-agnostic NPC simulation:
   events in, speech/actions/observations out, one pump per frame.
   Stdlib only, Python 3.11+.
2. **Forge** (`src/npc_cortex/forge/`) — turns game-design TOMLs into a
   full cast: validated specs, `story.md`, `skills.md`,
   short/long-term memories, per-type `skill-<npc-type>.md` playbooks,
   and model/latency/cost advice. A clarity gate refuses ambiguous
   contracts before anything is generated.
3. **Engine layer** (`src/npc_cortex/adapters/`, `clients/`) — one
   integration per engine, each with its own test file: in-process
   adapters for Python engines, native clients over HTTP for the
   rest.

Plus a complete demo game (**Maison Cinq**, `games/restaurant/`), a
pinned Docker smoke suite, and four agent skills (`skills/`) that
turn this repo's own history into reusable contracts.

## How it works

The per-frame contract is the same everywhere:

```text
sync transforms → submit events → pump → poll actions / delivered / observations
```

- In Python engines you call it directly (`attach_loop`,
  `adapters/panda3d.py`, …).
- In Unity, Unreal, Godot, Rust, and Bevy a native client performs
  the same flow against `BridgeServer` over HTTP
  (`docs/PROTOCOL.md`), with cursors so polls never replay.

NPCs perceive by distance and broadcast, speak through the provider,
and remember: per-actor histories, warm/wary/neutral dispositions,
and place familiarity that grows with localization (wandering →
fixed → rooted), intellect, and nearness to home — fixed NPCs know
their buildings inside out, including private interiors and hidden
details. Untrusted model output passes implication gating before it
can act; every decision lands in the audit log.

## Engines

| Engine | Integration | Code | Tests |
| --- | --- | --- | --- |
| Panda3D | in-process (`attach`) | `adapters/panda3d.py` | `tests/adapters/test_panda3d_attach.py` |
| Any frame loop | in-process (`FramePump`) | `adapters/loop.py` | `tests/adapters/test_loop.py` |
| Headless / no hook | background thread | `adapters/threaded.py` | `tests/adapters/test_threaded.py` |
| asyncio games & tools | task | `adapters/asyncio_adapter.py` | `tests/adapters/test_asyncio_adapter.py` |
| Godot (Python) | in-process | `adapters/godot.py` | `tests/adapters/test_godot.py` |
| pygame / arcade / pyglet | in-process | `adapters/pygame_adapter.py` | `tests/adapters/test_pygame.py` |
| Unity (C#) | network bridge | `clients/unity/` | `clients/unity/Tests/`, `tests/clients/test_unity_protocol.py` |
| Unreal (C++) | network bridge | `clients/unreal/` | `clients/unreal/*.spec.cpp`, `tests/clients/test_unreal_protocol.py` |
| Godot (GDScript) | network bridge | `clients/godot/` | `clients/godot/tests/`, `tests/clients/test_godot_protocol.py` |
| Rust (any engine) | network bridge | `clients/rust/` | `clients/rust/tests/`, `tests/clients/test_rust_protocol.py` |
| Bevy (Rust ECS) | plugin + worker | `clients/bevy/` | `clients/bevy/tests/`, `tests/clients/test_bevy_protocol.py` |

Positions are `(x, y)` or `(x, y, z)`; engine vectors map by identity
on components (distances are rotation-invariant). Details in
[`docs/ADAPTERS.md`](docs/ADAPTERS.md); the wire protocol in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md); client contracts in
[`skills/npc-cortex-engine-adapter/SKILL.md`](skills/npc-cortex-engine-adapter/SKILL.md).

## Quick start

### Any Python engine

```python
from npc_cortex import ActionRegistry, AuditLog, Event, Gateway, Runtime, Scenario
from npc_cortex.adapters.loop import attach_loop

runtime = Runtime(Scenario(...), provider, ActionRegistry(), Gateway(), AuditLog())
pump = attach_loop(runtime)

while running:      # your engine's loop
    pump.tick()     # one pump per frame
```

### Panda3D (original API, unchanged)

```python
import npc_cortex
npc_cortex.attach(runtime, task_mgr)
```

### Unity / Unreal / Godot / Rust over the network

```sh
python examples/bridge_server.py --port 8471
```

Then follow the per-frame flow from the native client in
`clients/<engine>/`. The reference Python client mirrors the same API:

```python
from npc_cortex.client import RemoteBridge
bridge = RemoteBridge("http://127.0.0.1:8471")
bridge.sync(players=[...], npcs=[...])
bridge.submit("direct_message", "n1", speaker_id="p1", text="hail")
bridge.pump()
for action in bridge.actions()["actions"]:
    execute_in_engine(action)   # accepted, implication-checked, ready to play
```

### Bevy

```rust
app.add_plugins(NpcCortexPlugin { base_url: url.into() });
// write SpeakRequest / SyncRequest / ... messages,
// read NpcSpeech / NpcObserved / ... messages; one Tick per frame.
```

All HTTP runs on a worker thread; a bounded command channel makes
slow frames skip instead of queue, so the game never stalls.

### Forge: generate the cast from TOML

```sh
# describe the game once, each quest as a scenario (see examples/forge/)
python - <<'EOF'
from npc_cortex.forge import NPCGenerator, advise, load_game, load_quest
game = load_game("examples/forge/medieval/game-description.toml")
quest = load_quest("examples/forge/medieval/game-quest-1.toml")
report = NPCGenerator(game, [quest]).run("out/emberfall")
print([s.id for s in report.npcs], report.skill_files)
EOF
```

Each NPC gets validated specs, `story.md`, `skills.md`,
`short-memory.json`, and `long-memory.json`; each type gets a
`skill-<npc-type>.md` playbook. Anything ambiguous in the TOMLs fails
the clarity gate with actionable errors instead of generating.

## Making the best use of it

1. **Describe before you generate.** Write `game-description.toml`
   (setting, locations, languages, NPC types, budgets) plus one
   `game-quest-<n>.toml` per scenario. Mark every NPC field `fixed`
   or explicitly `open` — the clarity gate (PASS needs zero errors
   and ≥ 80/100) is what guarantees generation quality.
2. **Follow the advice record.** Each (scenario, npc-type) pair gets
   a tiered `swift`/`balanced`/`deep` recommendation with timeouts
   fitted to your latency budget. Use `swift` for background crowds,
   `deep` for quest-critical dialogue.
3. **Keep the frame sacred.** One `pump()`/`Tick` per frame, cursored
   polls, bounded queues. If a model is slow, frames skip — they
   never wait.
4. **Protect the key.** End users acquire via `NPC_CORTEX_API_KEY`, a
   `0600` key file, or a guided prompt; keys are never logged
   (`...last4` display, redaction helper) and travel header-only.
5. **Extend through the skills.** New engine? New cast? The four
   skills below encode the contracts and their evaluations — any
   evaluation error means reiterate, not ship.

## Forge in depth

- **Contracts in.** `game-description.toml` plus `game-quest-<n>.toml`
  scenarios. Every NPC field is either fixed or explicitly `open`
  for generation.
- **Rubric #1 — clarity gate.** Scores schema, coverage, references,
  consistency, and clarity; PASS needs zero errors and ≥ 80/100, or
  generation refuses with `UnclearContract`.
- **16 personalities, setting-true names.** Four-axis profiles with
  medieval/scifi/modern titles and name banks, so a blacksmith is
  never called `Zx-417`.
- **Defined + generic NPCs.** Hand-authored characters keep their
  canon; the filler (seeded offline templates, or one LLM call per
  NPC) completes the rest per-time, per-location, per-scenario —
  with `fixed`/`template`/`llm` provenance per field.
- **Environment-aware NPCs.** Places live in the game TOML; each
  NPC's familiarity gates what they know. Knowledge lands in
  `awareness.md` and prompt context; live spatial queries come from
  `surroundings()` (runtime, bridge, and native clients).
- **Knowledge about each other.** Per-actor histories and long-term
  acquaintances develop as NPCs observe play; sessions persist via
  `export_memory` + `absorb`, and engines read it over
  `GET /v1/knowledge`.
- **Rubric #2 — model advice.** One tiered record per (scenario,
  npc-type) with example models and warnings when budgets can't
  host the demand.
- **Efficient.** Seeded determinism, manifest-cache skips for
  unchanged NPCs, and budgeted prompt packing for lore-heavy casts.

Contract: [`skills/npc-generation-contract/SKILL.md`](skills/npc-generation-contract/SKILL.md).
Evaluation: [`skills/npc-generation-evaluation/SKILL.md`](skills/npc-generation-evaluation/SKILL.md).
Examples: [`examples/forge/`](examples/forge) (medieval + scifi).

## Agent skills

Four skills generalize this repo's own development into reusable
contracts. Each contract skill has a companion evaluation skill;
**any error in an evaluation implies reiteration** — fix and
re-evaluate until the gate passes.

| Skill | Role |
| --- | --- |
| `skills/npc-cortex-engine-adapter/` | Contract: add a new engine (adapter or native client + mandatory per-engine test file). |
| `skills/npc-client-evaluation/` | Evaluation: protocol fidelity, frame-safety, error surfacing, and test rigor for a new client. |
| `skills/npc-generation-contract/` | Contract: generate NPCs from game/quest TOMLs through the clarity gate. |
| `skills/npc-generation-evaluation/` | Evaluation: clarity-gate rigor, name/setting truth, memory soundness, and advice quality. |

## Layout

- `src/npc_cortex/` — runtime core, `adapters/`, network `server/` +
  reference `client.py`, and the `forge/` generator. Stdlib only.
- `clients/{unity,unreal,godot,rust,bevy}/` — native clients + engine-side tests.
- `tests/` — core conformance plus one file per engine, bridge,
  client, and forge area.
- `skills/` — the four contract/evaluation skills above.
- `docs/` — `PROTOCOL.md` (wire API), `ADAPTERS.md` (engine table).
- `examples/` — minimal loop, bridge server, forge game TOMLs.
- `games/restaurant/` — the Maison Cinq demo game.

## Testing

```sh
pytest tests/   # 185 tests: core + adapters + bridge + clients + forge + games
```

Python adapters run without engine installs (Panda3D is faked when
absent; the Docker smoke uses the real one). Every native client
also ships tests in its own framework (Unity Test Framework, Unreal
Automation Specs, GUT, `cargo test`) — see `clients/<engine>/`.

## Games

**Maison Cinq** (`games/restaurant/`) — a demand-supply 2D game in a
5-star restaurant, driven by Panda3D tasks and npc-cortex NPCs
(full staff + flowing individuals, groups, friends and families,
multilingual personas, skills, memories), playable in a browser in
active role-play or passive-watch mode, with free movement, utility
actions, click-to-speak chats, and a multilogue transcript:

```sh
python3 games/restaurant/server.py --port 8901
# open http://127.0.0.1:8901
```

Dialogue is LLM-only: set `NPC_CORTEX_API_KEY` +
`NPC_CORTEX_ENDPOINT` + `NPC_CORTEX_MODEL` for live play, or
`NPC_CORTEX_FAKE_LLM=1` for the deterministic test stand-in. The
game authors its own `game-description.toml` + `game-quest-<n>.toml`
contracts (clarity 100/100).

## Docker smoke

Pinned, isolated, engine-wide (`Dockerfile` + `docker/smoke.sh`):
real-Panda3D pytest suite, Rust unit + live suites, Bevy headless
plugin tests, scripted game playthrough, native-client presence
check.

```sh
docker build -t npc-cortex-smoke .
docker run --rm npc-cortex-smoke   # ends with SMOKE-GREEN
```

## Compatibility

The runtime API and semantics are unchanged from the original
`npc-bridge` contract: the package import is the only breaking change
(`npc_bridge` → `npc_cortex`), alongside the new canonical env var
`NPC_CORTEX_API_KEY` (legacy `NPC_LLM_API_KEY` still works).
Positions additionally accept 3D; 2D behavior is identical.
