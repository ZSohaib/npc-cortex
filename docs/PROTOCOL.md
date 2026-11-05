# npc-cortex network protocol (v1)

Engines that cannot run Python in-process (Unity C#, Unreal C++, Godot
GDScript/C#) talk to a `BridgeServer` over HTTP+JSON. All endpoints live
under `/v1/`. Requests and responses are JSON objects (`Content-Type:
application/json`). The Python reference client is
`npc_cortex.client.RemoteBridge`; native clients mirror its method names.

Conventions:

* Positions are `[x, y]` or `[x, y, z]` arrays of numbers. Mapping from
  engine vectors is the identity on components (see
  `npc_cortex.adapters.unity/unreal/godot`).
* `since` parameters are feed cursors: pass back `next_since` (or
  `len` of what you consumed) to poll incrementally.
* Errors are `{"error": <name>, "detail": <str>}` with a status code:
  `400` bad request, `409` `Closed` (runtime shut down), `429`
  `Overloaded` (submit past capacity).

## Endpoints

### `GET /v1/health`

Liveness probe. No body.

```json
{ "ok": true, "engine": "npc-cortex", "version": "0.1.0" }
```

### `POST /v1/submit`

Submit an event. Mirrors `Runtime.submit()`.

```json
// request
{ "kind": "direct_message", "npc_id": "n1", "speaker_id": "p1", "text": "hello" }
// response 200
{ "ok": true }
```

`speaker_id` / `text` may be `null`. `429` when overloaded.

### `POST /v1/pump`

Resolve outstanding work. Mirrors `Runtime.pump()`; call once per frame.

```json
// request: {} (empty object)
// response 200
{ "resolved": 2 }
```

### `POST /v1/engage`

```json
// request
{ "player_id": "p1", "name": "escort", "parameters": {}, "duration": 5.0 }
// response 200
{ "handle": "engagement-1" }
```

### `POST /v1/cancel`

```json
// request
{ "handle": "engagement-1" }
// response 200
{ "ok": true }
```

### `GET /v1/observations?character_id=<id>`

```json
{ "records": [{ "handle": "", "actor_id": "n1", "action": "wave", "phase": "completed" }] }
```

### `GET /v1/memory?npc_id=<id>`

```json
{ "players": [], "npcs": [{ "actor_id": "n2", "action": "wave", "outcome": "completed" }] }
```

### `GET /v1/surroundings?npc_id=<id>&radius=20`

Live spatial sense: places near the NPC, nearest first. Observable
facts only (id, kind, distance, description, public) -- owners,
interiors, and hidden details stay behind forge familiarity and never
cross this endpoint.

```json
{ "places": [{ "id": "tavern", "kind": "building", "distance": 4.2,
  "description": "Warm tavern.", "public": true }] }
```

### `GET /v1/knowledge?npc_id=<id>&actor_id=<a>&limit=<n>`

What `npc_id` developed about others: `history` (received records,
oldest first, optionally one actor and/or the most recent `limit`) plus
`acquaintances` (`{actor: {interactions, completed, cancelled,
actions, first_seen, last_seen, disposition}}`, pump-epoch stamps,
`warm`/`wary`/`neutral`). `actor_id` and `limit` are optional.

```json
{ "history": [{ "handle": "", "actor_id": "n2", "action": "wave",
    "phase": "completed" }],
  "acquaintances": { "n2": { "interactions": 3, "completed": 3,
    "cancelled": 0, "actions": {"wave": 3}, "first_seen": 1,
    "last_seen": 4, "disposition": "warm" } } }
```

### `GET /v1/audit?since=0`

```json
{ "records": [{ "kind": "action_accepted", "npc_id": "n1", "event_kind": "tick", "detail": "wave" }], "next_since": 1 }
```

### `GET /v1/delivered?since=0`

Speech deliveries as `[player_id, text]` pairs, in order.

```json
{ "delivered": [["p1", "hello there"]], "next_since": 1 }
```

### `GET /v1/actions?since=0`

Applied remote-action feed. Each entry was accepted by the runtime
(shape-valid + implication satisfied); the engine executes it and,
when the action has visible effects, syncs the outcome back via the
observation records. Fire-and-forget: no acknowledgement endpoint.

```json
{
  "actions": [
    { "seq": 0, "handle": "", "actor_id": "n1", "npc_id": "n1",
      "name": "wave", "parameters": {}, "broadcast": false }
  ],
  "next_since": 1
}
```

Engagement completions appear here too, with `npc_id` `null` and
`handle`/`actor_id` empty (the runtime hands engagement handlers no
attribution); correlate them with engagement handles through the
`observations` records of the same pump, which carry both handle and
phase.

### `POST /v1/register_action`

Register a remote-executed action. Parameter types are JSON type names:
`str`, `int` (JSON number without fraction, `true`/`false` rejected),
`float` (any JSON number), `bool`, `dict`, `list`.

```json
// request
{ "name": "wave", "parameters": {"target": "str"},
  "min_implication": 0.2, "broadcast": false }
// response 200
{ "ok": true }
```

### `POST /v1/sync`

Upsert characters from engine state. Existing characters update only the
fields present; new players default to `role: "player"`,
`horizon: 10.0`, `online: true`; new NPCs default to `horizon: 10.0`,
`implication: 1.0`. `world_state`, when present, is shallow-merged.

```json
// request
{ "players": [{ "id": "p1", "position": [1, 0, 3], "online": true }],
  "npcs": [{ "id": "n1", "position": [4, 0, 3] }],
  "world_state": { "quest": "started" } }
// response 200
{ "ok": true, "players": 1, "npcs": 1 }
```

### `POST /v1/close`

Shut the runtime down. Later `submit`/`engage`/`pump` calls fail `Closed`.

```json
// request: {}
// response 200
{ "ok": true }
```

## Typical frame (Unity/Unreal/Godot client)

1. `sync` changed transforms (or every frame; it is cheap).
2. `submit` new dialogue/tick events.
3. `pump`, then poll `actions`, `delivered`, `observations` with cursors.
4. Execute fetched actions engine-side (play animation, move actor, ...).
