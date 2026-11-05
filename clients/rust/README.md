# npc-cortex (Rust)

Blocking Rust client for the npc-cortex HTTP bridge — for Bevy, Fyrox,
and engine-free tools. Mirrors `npc_cortex.client.RemoteBridge`.

```toml
[dependencies]
npc-cortex = { path = "../rust" }  # or version once published
```

```rust
use npc_cortex::{NpcCortexClient, SyncNpc, SyncPlayer};

let client = NpcCortexClient::new("http://127.0.0.1:8471");
let player = SyncPlayer::new("p1"); // set position/horizon as needed
let npc = SyncNpc::new("n1");
client.sync(&[player], &[npc], None)?;
client.submit("direct_message", "n1", Some("p1"), Some("hail"))?;
client.pump()?;
let (delivered, _) = client.delivered(0)?;
let (actions, _) = client.actions(0)?; // execute engine-side
```

Bevy tip: the client blocks, so drive it from a background thread
(`std::thread` + channels) and apply `actions`/`delivered` in a
system — never call `pump()` directly on the render thread.

Coordinates: `[x, y, z]` maps by identity on components
(`vec3_to_position`, `position_to_vec3`); see `adapters/rust.py` for
the shared convention.

Tests: `cargo test` runs the pure suite; start
`python examples/bridge_server.py --port 8471` and run
`cargo test -- --ignored` for the live suite.
