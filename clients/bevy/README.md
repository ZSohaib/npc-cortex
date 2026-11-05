# npc-cortex-bevy

Bevy client for the [npc-cortex HTTP bridge](../../docs/PROTOCOL.md):
one plugin, no frame stalls, speech and observations as ECS messages.

```rust
use bevy_app::App;
use npc_cortex_bevy::{NpcCortexPlugin, SpeakRequest};

App::new().add_plugins(NpcCortexPlugin {
    base_url: "http://127.0.0.1:8901".to_string(),
});
```

## Flow

Every frame the plugin sends one `Tick` to a background worker thread
that owns the blocking HTTP client: `sync` -> `submit` -> `pump` ->
poll `delivered` / `actions` with cursors. The command channel is
bounded (32): when the server lags, frames skip instead of queueing.

Games write request messages (`SpeakRequest`, `SyncRequest`,
`ObserveRequest`, `EngageRequest`, `CancelRequest`,
`RegisterActionRequest`, `MemoryRequest`, `AuditRequest`,
`SurroundingsRequest`, `KnowledgeRequest`, `HealthRequest`,
`CloseRequest`) and read result messages (`NpcSpeech`, `NpcObserved`,
`NpcActionRaised`, `EngagementOpened`, `MemoryReceived`,
`AuditReceived`, `SurroundingsReceived`, `KnowledgeReceived`,
`HealthReceived`); request/response pairs correlate by `request_id`,
and `CortexErrorRaised` surfaces bridge failures instead of
panicking.

## Coordinates

Bevy `Vec3` maps identity on components (`[x, y, z]` -> `[x, y, z]`);
npc-cortex distances are rotation-invariant so y-up needs no
conversion. See `to_cortex_vec3` / `from_cortex_position`.

## Versions

Built against `bevy_ecs` / `bevy_app` 0.20 (see `Cargo.toml` / `Cargo.lock`);
the plugin must match the minor version of the game's own Bevy.

## Checks

```sh
cargo build
cargo test
```
