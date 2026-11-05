//! Bevy client for the npc-cortex HTTP bridge (`docs/PROTOCOL.md`).
//!
//! [`NpcCortexPlugin`] wires one bridge server into a Bevy [`App`](bevy_app::App):
//! games write request messages ([`SpeakRequest`], [`SyncRequest`],
//! [`ObserveRequest`], [`EngageRequest`], [`CancelRequest`],
//! [`RegisterActionRequest`], [`MemoryRequest`], [`AuditRequest`],
//! [`SurroundingsRequest`], [`KnowledgeRequest`], [`HealthRequest`],
//! [`CloseRequest`]), one background worker owns the blocking HTTP client
//! and the poll cursors, and results arrive as [`NpcSpeech`],
//! [`NpcObserved`], [`NpcActionRaised`], [`EngagementOpened`],
//! [`MemoryReceived`], [`AuditReceived`], [`SurroundingsReceived`],
//! [`KnowledgeReceived`], [`HealthReceived`], and [`CortexErrorRaised`]
//! messages. The frame loop never blocks: all HTTP runs on the worker
//! thread, systems only move messages, and a bounded command channel
//! makes slow frames skip instead of queue.
//!
//! Coordinate convention: a Bevy `Vec3` maps identity on components
//! (`[x, y, z]` -> `[x, y, z]`, see [`to_cortex_vec3`]); npc-cortex
//! distances are rotation-invariant so y-up needs no conversion.

use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, Sender, SyncSender, TrySendError};
use std::thread::JoinHandle;

use bevy_app::{App, Plugin, Update};
use bevy_ecs::message::{Message, MessageReader, MessageWriter};
use bevy_ecs::resource::Resource;
use bevy_ecs::system::Res;

pub use npc_cortex::{
    Acquaintance, AuditRecord, CortexError, Memory, MemoryEntry, NearbyPlace, NpcCortexClient,
    Observation, RemoteAction, SyncNpc, SyncPlayer,
};

// ---------------------------------------------------------------------------
// coordinate mapping (pure, unit-tested)
// ---------------------------------------------------------------------------

/// Bevy `Vec3` -> npc position (identity on components).
pub fn to_cortex_vec3(v: [f32; 3]) -> [f64; 3] {
    [v[0] as f64, v[1] as f64, v[2] as f64]
}

/// npc position -> Bevy `Vec3` (missing components become `0.0`).
pub fn from_cortex_position(p: &[f64]) -> [f32; 3] {
    let at = |i: usize| p.get(i).copied().unwrap_or(0.0) as f32;
    [at(0), at(1), at(2)]
}

// ---------------------------------------------------------------------------
// messages: game <-> bridge
// ---------------------------------------------------------------------------

/// Ask the bridge to resolve one event for an NPC.
#[derive(Message, Debug, Clone)]
pub struct SpeakRequest {
    pub kind: String,
    pub npc_id: String,
    pub speaker_id: Option<String>,
    pub text: Option<String>,
}

impl SpeakRequest {
    /// A line addressed to an NPC (`kind = "direct_message"`).
    pub fn say(npc_id: &str, speaker_id: &str, text: &str) -> Self {
        SpeakRequest {
            kind: "direct_message".to_string(),
            npc_id: npc_id.to_string(),
            speaker_id: Some(speaker_id.to_string()),
            text: Some(text.to_string()),
        }
    }

    /// A thinking tick for an NPC (`kind = "tick"`).
    pub fn tick(npc_id: &str) -> Self {
        SpeakRequest {
            kind: "tick".to_string(),
            npc_id: npc_id.to_string(),
            speaker_id: None,
            text: None,
        }
    }
}

/// Push transforms to the bridge (`sync` -> `submit` -> `pump` flow).
#[derive(Message, Debug, Clone, Default)]
pub struct SyncRequest {
    pub players: Vec<SyncPlayer>,
    pub npcs: Vec<SyncNpc>,
}

/// Ask for one character's observations.
#[derive(Message, Debug, Clone)]
pub struct ObserveRequest {
    pub character_id: String,
}

/// A resolved line, delivered to its recipient.
#[derive(Message, Debug, Clone)]
pub struct NpcSpeech {
    pub recipient_id: String,
    pub text: String,
}

/// Observations for one character (carries speaker attribution).
#[derive(Message, Debug, Clone)]
pub struct NpcObserved {
    pub character_id: String,
    pub observations: Vec<Observation>,
}

/// A runtime action raised since the last poll.
#[derive(Message, Debug, Clone)]
pub struct NpcActionRaised {
    pub action: RemoteAction,
}

/// A bridge failure, surfaced instead of panicking.
#[derive(Message, Debug, Clone)]
pub struct CortexErrorRaised {
    pub detail: String,
}

/// Open an engagement (`request_id` echoes back on [`EngagementOpened`]).
#[derive(Message, Debug, Clone)]
pub struct EngageRequest {
    pub request_id: u64,
    pub player_id: String,
    pub name: String,
    pub parameters: HashMap<String, serde_json::Value>,
    pub duration: f64,
}

/// The handle for an [`EngageRequest`].
#[derive(Message, Debug, Clone)]
pub struct EngagementOpened {
    pub request_id: u64,
    pub handle: String,
}

/// Cancel an engagement (fire-and-forget; inert on unknown handles).
#[derive(Message, Debug, Clone)]
pub struct CancelRequest {
    pub handle: String,
}

/// Register a runtime action (fire-and-forget).
#[derive(Message, Debug, Clone)]
pub struct RegisterActionRequest {
    pub name: String,
    pub parameters: HashMap<String, String>,
    pub min_implication: f64,
    pub broadcast: bool,
}

/// Ask for one NPC's memory (`request_id` echoes on [`MemoryReceived`]).
#[derive(Message, Debug, Clone)]
pub struct MemoryRequest {
    pub request_id: u64,
    pub npc_id: String,
}

/// The memory for a [`MemoryRequest`].
#[derive(Message, Debug, Clone)]
pub struct MemoryReceived {
    pub request_id: u64,
    pub memory: Memory,
}

/// Ask for audit records since a cursor.
#[derive(Message, Debug, Clone)]
pub struct AuditRequest {
    pub request_id: u64,
    pub since: i64,
}

/// The records for an [`AuditRequest`], plus the next cursor.
#[derive(Message, Debug, Clone)]
pub struct AuditReceived {
    pub request_id: u64,
    pub records: Vec<AuditRecord>,
    pub next_since: i64,
}

/// Ask what is around one NPC.
#[derive(Message, Debug, Clone)]
pub struct SurroundingsRequest {
    pub request_id: u64,
    pub npc_id: String,
    pub radius: f64,
}

/// The places for a [`SurroundingsRequest`].
#[derive(Message, Debug, Clone)]
pub struct SurroundingsReceived {
    pub request_id: u64,
    pub places: Vec<NearbyPlace>,
}

/// Ask for history + acquaintances.
#[derive(Message, Debug, Clone)]
pub struct KnowledgeRequest {
    pub request_id: u64,
    pub npc_id: String,
    pub actor_id: Option<String>,
    pub limit: Option<i64>,
}

/// The knowledge for a [`KnowledgeRequest`].
#[derive(Message, Debug, Clone)]
pub struct KnowledgeReceived {
    pub request_id: u64,
    pub history: Vec<Observation>,
    pub acquaintances: HashMap<String, Acquaintance>,
}

/// Ask for a health probe.
#[derive(Message, Debug, Clone)]
pub struct HealthRequest {
    pub request_id: u64,
}

/// The health payload for a [`HealthRequest`].
#[derive(Message, Debug, Clone)]
pub struct HealthReceived {
    pub request_id: u64,
    pub status: serde_json::Value,
}

/// Close the bridge. Ticks go quiet afterwards, but the worker stays
/// up so queries still round-trip (the server answers `Closed`);
/// drop the `App` (or `shutdown`) to end the thread.
#[derive(Message, Debug, Clone)]
pub struct CloseRequest;

// ---------------------------------------------------------------------------
// worker protocol (private)
// ---------------------------------------------------------------------------

enum WorkerCmd {
    Speak {
        kind: String,
        npc_id: String,
        speaker_id: Option<String>,
        text: Option<String>,
    },
    Sync {
        players: Vec<SyncPlayer>,
        npcs: Vec<SyncNpc>,
    },
    Observe {
        character_id: String,
    },
    Engage {
        request_id: u64,
        player_id: String,
        name: String,
        parameters: HashMap<String, serde_json::Value>,
        duration: f64,
    },
    Cancel {
        handle: String,
    },
    RegisterAction {
        name: String,
        parameters: HashMap<String, String>,
        min_implication: f64,
        broadcast: bool,
    },
    Memory {
        request_id: u64,
        npc_id: String,
    },
    Audit {
        request_id: u64,
        since: i64,
    },
    Surroundings {
        request_id: u64,
        npc_id: String,
        radius: f64,
    },
    Knowledge {
        request_id: u64,
        npc_id: String,
        actor_id: Option<String>,
        limit: Option<i64>,
    },
    Health {
        request_id: u64,
    },
    Close,
    Tick,
    Shutdown,
}

enum WorkerOut {
    Speech {
        recipient_id: String,
        text: String,
    },
    Observed {
        character_id: String,
        observations: Vec<Observation>,
    },
    Action(RemoteAction),
    Engaged {
        request_id: u64,
        handle: String,
    },
    Memory {
        request_id: u64,
        memory: Memory,
    },
    Audit {
        request_id: u64,
        records: Vec<AuditRecord>,
        next_since: i64,
    },
    Surroundings {
        request_id: u64,
        places: Vec<NearbyPlace>,
    },
    Knowledge {
        request_id: u64,
        history: Vec<Observation>,
        acquaintances: HashMap<String, Acquaintance>,
    },
    Health {
        request_id: u64,
        status: serde_json::Value,
    },
    Err(String),
}

fn worker_main(client: NpcCortexClient, rx: Receiver<WorkerCmd>, tx: Sender<WorkerOut>) {
    let mut delivered_since = 0i64;
    let mut actions_since = 0i64;
    let mut closed = false;
    loop {
        // Block for the first command so the thread idles cheaply, then
        // drain everything queued: one pump per frame worth of work.
        let first = match rx.recv() {
            Ok(cmd) => cmd,
            Err(_) => break,
        };
        let mut cmds = vec![first];
        while let Ok(cmd) = rx.try_recv() {
            cmds.push(cmd);
        }
        let mut tick = false;
        for cmd in cmds {
            match cmd {
                WorkerCmd::Shutdown => return,
                WorkerCmd::Speak {
                    kind,
                    npc_id,
                    speaker_id,
                    text,
                } => {
                    if let Err(e) =
                        client.submit(&kind, &npc_id, speaker_id.as_deref(), text.as_deref())
                    {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                }
                WorkerCmd::Sync { players, npcs } => {
                    if let Err(e) = client.sync(&players, &npcs, None) {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                }
                WorkerCmd::Observe { character_id } => match client.observations(&character_id) {
                    Ok(records) => {
                        let _ = tx.send(WorkerOut::Observed {
                            character_id,
                            observations: records,
                        });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Engage {
                    request_id,
                    player_id,
                    name,
                    parameters,
                    duration,
                } => match client.engage(&player_id, &name, &parameters, duration) {
                    Ok(handle) => {
                        let _ = tx.send(WorkerOut::Engaged { request_id, handle });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Cancel { handle } => {
                    if let Err(e) = client.cancel(&handle) {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                }
                WorkerCmd::RegisterAction {
                    name,
                    parameters,
                    min_implication,
                    broadcast,
                } => {
                    if let Err(e) =
                        client.register_action(&name, &parameters, min_implication, broadcast)
                    {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                }
                WorkerCmd::Memory { request_id, npc_id } => match client.memory(&npc_id) {
                    Ok(memory) => {
                        let _ = tx.send(WorkerOut::Memory { request_id, memory });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Audit { request_id, since } => match client.audit(since) {
                    Ok((records, next_since)) => {
                        let _ = tx.send(WorkerOut::Audit {
                            request_id,
                            records,
                            next_since,
                        });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Surroundings {
                    request_id,
                    npc_id,
                    radius,
                } => match client.surroundings(&npc_id, radius) {
                    Ok(places) => {
                        let _ = tx.send(WorkerOut::Surroundings { request_id, places });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Knowledge {
                    request_id,
                    npc_id,
                    actor_id,
                    limit,
                } => match client.knowledge(&npc_id, actor_id.as_deref(), limit) {
                    Ok((history, acquaintances)) => {
                        let _ = tx.send(WorkerOut::Knowledge {
                            request_id,
                            history,
                            acquaintances,
                        });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Health { request_id } => match client.health() {
                    Ok(status) => {
                        let _ = tx.send(WorkerOut::Health { request_id, status });
                    }
                    Err(e) => {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                },
                WorkerCmd::Close => {
                    if let Err(e) = client.close() {
                        let _ = tx.send(WorkerOut::Err(e.to_string()));
                    }
                    closed = true;
                }
                WorkerCmd::Tick => tick = true,
            }
        }
        if tick && !closed {
            if let Err(e) = client.pump() {
                let _ = tx.send(WorkerOut::Err(e.to_string()));
                continue;
            }
            match client.delivered(delivered_since) {
                Ok((lines, next)) => {
                    delivered_since = next;
                    for (recipient_id, text) in lines {
                        let _ = tx.send(WorkerOut::Speech { recipient_id, text });
                    }
                }
                Err(e) => {
                    let _ = tx.send(WorkerOut::Err(e.to_string()));
                }
            }
            match client.actions(actions_since) {
                Ok((raised, next)) => {
                    actions_since = next;
                    for action in raised {
                        let _ = tx.send(WorkerOut::Action(action));
                    }
                }
                Err(e) => {
                    let _ = tx.send(WorkerOut::Err(e.to_string()));
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// resources + plugin
// ---------------------------------------------------------------------------

/// Handle to the bridge worker. Clone it into your own systems to speak
/// or sync outside the message flow.
///
/// The command channel is bounded: when the server lags, frames skip
/// (commands drop) instead of queueing, so recovery never replays a
/// backlog of stale ticks.
#[derive(Resource, Clone)]
pub struct CortexBridge {
    cmd: SyncSender<WorkerCmd>,
}

impl CortexBridge {
    fn push(&self, cmd: WorkerCmd) {
        match self.cmd.try_send(cmd) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {} // skip, don't queue
            Err(TrySendError::Disconnected(_)) => {}
        }
    }

    /// Queue one event without touching the message bus.
    pub fn speak(&self, kind: &str, npc_id: &str, speaker_id: Option<&str>, text: Option<&str>) {
        self.push(WorkerCmd::Speak {
            kind: kind.to_string(),
            npc_id: npc_id.to_string(),
            speaker_id: speaker_id.map(str::to_string),
            text: text.map(str::to_string),
        });
    }

    /// Shut the worker thread down (also runs automatically on App exit).
    /// Blocking: shutdown must land, so this waits for channel space.
    pub fn shutdown(&self) {
        let _ = self.cmd.send(WorkerCmd::Shutdown);
    }
}

/// Inbox of worker results. Plain mutex: `Receiver` is `Send`, so no
/// `NonSend` machinery is needed and any system can drain it.
#[derive(Resource)]
pub struct CortexInbox {
    rx: std::sync::Mutex<Receiver<WorkerOut>>,
}

/// Joins the worker when the `App` drops so test binaries exit cleanly.
#[derive(Resource)]
struct WorkerGuard {
    tx: SyncSender<WorkerCmd>,
    handle: Option<JoinHandle<()>>,
}

impl Drop for WorkerGuard {
    fn drop(&mut self) {
        let _ = self.tx.send(WorkerCmd::Shutdown);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

/// Adds npc-cortex speech + observations to an [`App`].
///
/// ```no_run
/// use bevy_app::App;
/// use npc_cortex_bevy::NpcCortexPlugin;
///
/// App::new().add_plugins(NpcCortexPlugin {
///     base_url: "http://127.0.0.1:8901".to_string(),
/// });
/// ```
#[derive(Clone)]
pub struct NpcCortexPlugin {
    pub base_url: String,
}

impl Plugin for NpcCortexPlugin {
    fn build(&self, app: &mut App) {
        let client = NpcCortexClient::new(&self.base_url);
        let (cmd_tx, cmd_rx) = mpsc::sync_channel(32);
        let (out_tx, out_rx) = mpsc::channel();
        let handle = std::thread::Builder::new()
            .name("npc-cortex-worker".to_string())
            .spawn(move || worker_main(client, cmd_rx, out_tx))
            .expect("spawn npc-cortex worker");
        app.insert_resource(CortexBridge {
            cmd: cmd_tx.clone(),
        });
        app.insert_resource(CortexInbox {
            rx: std::sync::Mutex::new(out_rx),
        });
        app.insert_resource(WorkerGuard {
            tx: cmd_tx,
            handle: Some(handle),
        });
        app.add_message::<SpeakRequest>();
        app.add_message::<SyncRequest>();
        app.add_message::<ObserveRequest>();
        app.add_message::<EngageRequest>();
        app.add_message::<CancelRequest>();
        app.add_message::<RegisterActionRequest>();
        app.add_message::<MemoryRequest>();
        app.add_message::<AuditRequest>();
        app.add_message::<SurroundingsRequest>();
        app.add_message::<KnowledgeRequest>();
        app.add_message::<HealthRequest>();
        app.add_message::<CloseRequest>();
        app.add_message::<NpcSpeech>();
        app.add_message::<NpcObserved>();
        app.add_message::<NpcActionRaised>();
        app.add_message::<EngagementOpened>();
        app.add_message::<MemoryReceived>();
        app.add_message::<AuditReceived>();
        app.add_message::<SurroundingsReceived>();
        app.add_message::<KnowledgeReceived>();
        app.add_message::<HealthReceived>();
        app.add_message::<CortexErrorRaised>();
        app.add_systems(Update, (forward_requests, pump_bridge, forward_results));
    }
}

#[allow(clippy::too_many_arguments)]
fn forward_requests(
    bridge: Res<CortexBridge>,
    mut speak: MessageReader<SpeakRequest>,
    mut sync: MessageReader<SyncRequest>,
    mut observe: MessageReader<ObserveRequest>,
    mut engage: MessageReader<EngageRequest>,
    mut cancel: MessageReader<CancelRequest>,
    mut register: MessageReader<RegisterActionRequest>,
    mut memory: MessageReader<MemoryRequest>,
    mut audit: MessageReader<AuditRequest>,
    mut surroundings: MessageReader<SurroundingsRequest>,
    mut knowledge: MessageReader<KnowledgeRequest>,
    mut health: MessageReader<HealthRequest>,
    mut close: MessageReader<CloseRequest>,
) {
    for req in speak.read() {
        bridge.speak(
            &req.kind,
            &req.npc_id,
            req.speaker_id.as_deref(),
            req.text.as_deref(),
        );
    }
    for req in sync.read() {
        bridge.push(WorkerCmd::Sync {
            players: req.players.clone(),
            npcs: req.npcs.clone(),
        });
    }
    for req in observe.read() {
        bridge.push(WorkerCmd::Observe {
            character_id: req.character_id.clone(),
        });
    }
    for req in engage.read() {
        bridge.push(WorkerCmd::Engage {
            request_id: req.request_id,
            player_id: req.player_id.clone(),
            name: req.name.clone(),
            parameters: req.parameters.clone(),
            duration: req.duration,
        });
    }
    for req in cancel.read() {
        bridge.push(WorkerCmd::Cancel {
            handle: req.handle.clone(),
        });
    }
    for req in register.read() {
        bridge.push(WorkerCmd::RegisterAction {
            name: req.name.clone(),
            parameters: req.parameters.clone(),
            min_implication: req.min_implication,
            broadcast: req.broadcast,
        });
    }
    for req in memory.read() {
        bridge.push(WorkerCmd::Memory {
            request_id: req.request_id,
            npc_id: req.npc_id.clone(),
        });
    }
    for req in audit.read() {
        bridge.push(WorkerCmd::Audit {
            request_id: req.request_id,
            since: req.since,
        });
    }
    for req in surroundings.read() {
        bridge.push(WorkerCmd::Surroundings {
            request_id: req.request_id,
            npc_id: req.npc_id.clone(),
            radius: req.radius,
        });
    }
    for req in knowledge.read() {
        bridge.push(WorkerCmd::Knowledge {
            request_id: req.request_id,
            npc_id: req.npc_id.clone(),
            actor_id: req.actor_id.clone(),
            limit: req.limit,
        });
    }
    for req in health.read() {
        bridge.push(WorkerCmd::Health {
            request_id: req.request_id,
        });
    }
    for _ in close.read() {
        bridge.push(WorkerCmd::Close);
    }
}

fn pump_bridge(bridge: Res<CortexBridge>) {
    bridge.push(WorkerCmd::Tick);
}

#[allow(clippy::too_many_arguments)]
fn forward_results(
    inbox: Res<CortexInbox>,
    mut speech: MessageWriter<NpcSpeech>,
    mut observed: MessageWriter<NpcObserved>,
    mut actions: MessageWriter<NpcActionRaised>,
    mut engaged: MessageWriter<EngagementOpened>,
    mut memories: MessageWriter<MemoryReceived>,
    mut audit: MessageWriter<AuditReceived>,
    mut surroundings: MessageWriter<SurroundingsReceived>,
    mut knowledge: MessageWriter<KnowledgeReceived>,
    mut health: MessageWriter<HealthReceived>,
    mut errors: MessageWriter<CortexErrorRaised>,
) {
    let rx = match inbox.rx.lock() {
        Ok(guard) => guard,
        Err(_) => return,
    };
    while let Ok(out) = rx.try_recv() {
        match out {
            WorkerOut::Speech { recipient_id, text } => {
                speech.write(NpcSpeech { recipient_id, text });
            }
            WorkerOut::Observed {
                character_id,
                observations,
            } => {
                observed.write(NpcObserved {
                    character_id,
                    observations,
                });
            }
            WorkerOut::Action(action) => {
                actions.write(NpcActionRaised { action });
            }
            WorkerOut::Engaged { request_id, handle } => {
                engaged.write(EngagementOpened { request_id, handle });
            }
            WorkerOut::Memory { request_id, memory } => {
                memories.write(MemoryReceived { request_id, memory });
            }
            WorkerOut::Audit {
                request_id,
                records,
                next_since,
            } => {
                audit.write(AuditReceived {
                    request_id,
                    records,
                    next_since,
                });
            }
            WorkerOut::Surroundings { request_id, places } => {
                surroundings.write(SurroundingsReceived { request_id, places });
            }
            WorkerOut::Knowledge {
                request_id,
                history,
                acquaintances,
            } => {
                knowledge.write(KnowledgeReceived {
                    request_id,
                    history,
                    acquaintances,
                });
            }
            WorkerOut::Health { request_id, status } => {
                health.write(HealthReceived { request_id, status });
            }
            WorkerOut::Err(detail) => {
                errors.write(CortexErrorRaised { detail });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vec3_mapping_round_trips_by_identity() {
        let bevy = [7.0f32, 1.0, -2.0];
        let pos = to_cortex_vec3(bevy);
        assert_eq!(pos, [7.0, 1.0, -2.0]);
        let back = from_cortex_position(&pos);
        assert_eq!(back, bevy);
    }

    #[test]
    fn vec2_positions_gain_zero_z() {
        assert_eq!(from_cortex_position(&[4.0, 5.0]), [4.0, 5.0, 0.0]);
    }

    #[test]
    fn short_positions_never_panic() {
        assert_eq!(from_cortex_position(&[]), [0.0, 0.0, 0.0]);
        assert_eq!(from_cortex_position(&[9.0]), [9.0, 0.0, 0.0]);
    }
}
