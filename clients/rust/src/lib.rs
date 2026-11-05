//! Rust client for the npc-cortex HTTP bridge (`docs/PROTOCOL.md`).
//!
//! Mirrors `npc_cortex.client.RemoteBridge` method for method. Blocking
//! (`ureq`): call from a background thread or sparingly from a Bevy
//! system so the frame loop never stalls.
//!
//! Coordinate convention: `[x, y, z]` maps to `[x, y, z]` (identity on
//! components, see `adapters/rust.py`). Bevy is y-up like Unity; the
//! mapping needs no conversion because npc-cortex distances are
//! rotation-invariant.

use std::collections::HashMap;
use std::time::Duration;

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// errors
// ---------------------------------------------------------------------------

/// What can go wrong on the wire. `Overloaded` (HTTP 429) and `Closed`
/// (HTTP 409) mirror the runtime's exceptions.
#[derive(Debug)]
pub enum CortexError {
    Overloaded(String),
    Closed(String),
    Bridge(String),
    Transport(String),
    Json(String),
}

impl std::fmt::Display for CortexError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CortexError::Overloaded(d) => write!(f, "overloaded: {d}"),
            CortexError::Closed(d) => write!(f, "closed: {d}"),
            CortexError::Bridge(d) => write!(f, "bridge: {d}"),
            CortexError::Transport(d) => write!(f, "transport: {d}"),
            CortexError::Json(d) => write!(f, "json: {d}"),
        }
    }
}

impl std::error::Error for CortexError {}

// ---------------------------------------------------------------------------
// DTOs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Observation {
    pub handle: String,
    pub actor_id: String,
    pub action: String,
    pub phase: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MemoryEntry {
    pub actor_id: String,
    pub action: String,
    pub outcome: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Memory {
    #[serde(default)]
    pub players: Vec<MemoryEntry>,
    #[serde(default)]
    pub npcs: Vec<MemoryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AuditRecord {
    pub kind: String,
    pub npc_id: String,
    pub event_kind: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteAction {
    pub seq: i64,
    pub handle: String,
    pub actor_id: String,
    pub npc_id: Option<String>,
    pub name: String,
    #[serde(default)]
    pub parameters: serde_json::Map<String, serde_json::Value>,
    pub broadcast: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NearbyPlace {
    pub id: String,
    pub kind: String,
    pub distance: f64,
    pub description: String,
    #[serde(rename = "public")]
    pub is_public: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Acquaintance {
    pub interactions: u64,
    pub completed: u64,
    pub cancelled: u64,
    #[serde(default)]
    pub actions: HashMap<String, u64>,
    pub first_seen: u64,
    pub last_seen: u64,
    pub disposition: String,
}

/// Player transform for `/v1/sync`. Only `id` is required; `None`
/// fields are omitted and leave server state untouched.
#[derive(Debug, Clone, Serialize, Default)]
pub struct SyncPlayer {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position: Option<Vec<f64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub horizon: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub online: Option<bool>,
}

impl SyncPlayer {
    pub fn new(id: &str) -> Self {
        SyncPlayer {
            id: id.to_string(),
            ..Default::default()
        }
    }
}

/// NPC transform for `/v1/sync`.
#[derive(Debug, Clone, Serialize, Default)]
pub struct SyncNpc {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position: Option<Vec<f64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub horizon: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub implication: Option<f64>,
}

impl SyncNpc {
    pub fn new(id: &str) -> Self {
        SyncNpc {
            id: id.to_string(),
            ..Default::default()
        }
    }
}

// response envelopes (private)
#[derive(Deserialize)]
struct PumpResp {
    resolved: i64,
}

#[derive(Deserialize)]
struct HandleResp {
    handle: String,
}

#[derive(Deserialize)]
struct Records<T> {
    records: Vec<T>,
}

#[derive(Deserialize)]
struct Feed<T> {
    records: Vec<T>,
    next_since: i64,
}

#[derive(Deserialize)]
struct DeliveredResp {
    delivered: Vec<(String, String)>,
    next_since: i64,
}

#[derive(Deserialize)]
struct ActionsResp {
    actions: Vec<RemoteAction>,
    next_since: i64,
}

#[derive(Deserialize)]
struct PlacesResp {
    places: Vec<NearbyPlace>,
}

#[derive(Deserialize)]
struct KnowledgeResp {
    history: Vec<Observation>,
    acquaintances: HashMap<String, Acquaintance>,
}

// ---------------------------------------------------------------------------
// pure helpers (unit-tested, no HTTP)
// ---------------------------------------------------------------------------

/// `[x, y, z]` engine vector -> npc position (identity on components).
pub fn vec3_to_position(x: f64, y: f64, z: f64) -> [f64; 3] {
    [x, y, z]
}

/// `[x, y]` engine vector -> npc position.
pub fn vec2_to_position(x: f64, y: f64) -> [f64; 2] {
    [x, y]
}

/// npc position -> `[x, y, z]` (missing `z` becomes `0.0`).
pub fn position_to_vec3(p: &[f64]) -> [f64; 3] {
    [p[0], p[1], if p.len() > 2 { p[2] } else { 0.0 }]
}

/// npc position -> `[x, y]` (drops `z`).
pub fn position_to_vec2(p: &[f64]) -> [f64; 2] {
    [p[0], p[1]]
}

/// Build the JSON body for `POST /v1/submit`.
pub fn build_submit_body(
    kind: &str,
    npc_id: &str,
    speaker_id: Option<&str>,
    text: Option<&str>,
) -> String {
    serde_json::json!({
        "kind": kind,
        "npc_id": npc_id,
        "speaker_id": speaker_id,
        "text": text,
    })
    .to_string()
}

/// Parse a `POST /v1/pump` response; `None` when malformed.
pub fn parse_pump_response(body: &str) -> Option<i64> {
    serde_json::from_str::<PumpResp>(body)
        .ok()
        .map(|r| r.resolved)
}

/// Minimal percent-encoding for query values.
pub fn percent_encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for b in value.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

// ---------------------------------------------------------------------------
// client
// ---------------------------------------------------------------------------

/// Blocking client for one bridge server.
pub struct NpcCortexClient {
    base_url: String,
    agent: ureq::Agent,
}

impl NpcCortexClient {
    pub fn new(base_url: &str) -> Self {
        Self::with_timeout(base_url, Duration::from_secs(10))
    }

    pub fn with_timeout(base_url: &str, timeout: Duration) -> Self {
        NpcCortexClient {
            base_url: base_url.trim_end_matches('/').to_string(),
            agent: ureq::AgentBuilder::new().timeout(timeout).build(),
        }
    }

    fn post<T: serde::de::DeserializeOwned>(
        &self,
        path: &str,
        body: &impl Serialize,
    ) -> Result<T, CortexError> {
        let payload = serde_json::to_string(body).map_err(|e| CortexError::Json(e.to_string()))?;
        let url = format!("{}{}", self.base_url, path);
        match self
            .agent
            .post(&url)
            .set("Content-Type", "application/json")
            .send_string(&payload)
        {
            Ok(resp) => Self::read(resp),
            Err(e) => Err(Self::transport(e)),
        }
    }

    fn get<T: serde::de::DeserializeOwned>(&self, path: &str) -> Result<T, CortexError> {
        let url = format!("{}{}", self.base_url, path);
        match self.agent.get(&url).call() {
            Ok(resp) => Self::read(resp),
            Err(e) => Err(Self::transport(e)),
        }
    }

    fn read<T: serde::de::DeserializeOwned>(resp: ureq::Response) -> Result<T, CortexError> {
        let text = resp
            .into_string()
            .map_err(|e| CortexError::Transport(e.to_string()))?;
        serde_json::from_str(&text).map_err(|e| CortexError::Json(e.to_string()))
    }

    fn transport(err: ureq::Error) -> CortexError {
        match err {
            ureq::Error::Status(code, resp) => {
                let text = resp.into_string().unwrap_or_default();
                let (name, detail) = parse_error_body(&text);
                if code == 429 || name == "Overloaded" {
                    CortexError::Overloaded(detail)
                } else if code == 409 || name == "Closed" {
                    CortexError::Closed(detail)
                } else {
                    CortexError::Bridge(format!("{name}: {detail}"))
                }
            }
            other => CortexError::Transport(other.to_string()),
        }
    }

    // -- runtime mirror ------------------------------------------------------

    pub fn health(&self) -> Result<serde_json::Value, CortexError> {
        self.get("/v1/health")
    }

    pub fn submit(
        &self,
        kind: &str,
        npc_id: &str,
        speaker_id: Option<&str>,
        text: Option<&str>,
    ) -> Result<(), CortexError> {
        let body = serde_json::json!({
            "kind": kind,
            "npc_id": npc_id,
            "speaker_id": speaker_id,
            "text": text,
        });
        self.post::<serde_json::Value>("/v1/submit", &body)
            .map(|_| ())
    }

    pub fn pump(&self) -> Result<i64, CortexError> {
        self.post::<PumpResp>("/v1/pump", &serde_json::json!({}))
            .map(|r| r.resolved)
    }

    pub fn engage(
        &self,
        player_id: &str,
        name: &str,
        parameters: &HashMap<String, serde_json::Value>,
        duration: f64,
    ) -> Result<String, CortexError> {
        let body = serde_json::json!({
            "player_id": player_id,
            "name": name,
            "parameters": parameters,
            "duration": duration,
        });
        self.post::<HandleResp>("/v1/engage", &body)
            .map(|r| r.handle)
    }

    pub fn cancel(&self, handle: &str) -> Result<(), CortexError> {
        let body = serde_json::json!({ "handle": handle });
        self.post::<serde_json::Value>("/v1/cancel", &body)
            .map(|_| ())
    }

    pub fn observations(&self, character_id: &str) -> Result<Vec<Observation>, CortexError> {
        let path = format!(
            "/v1/observations?character_id={}",
            percent_encode(character_id)
        );
        self.get::<Records<Observation>>(&path).map(|r| r.records)
    }

    pub fn memory(&self, npc_id: &str) -> Result<Memory, CortexError> {
        self.get(&format!("/v1/memory?npc_id={}", percent_encode(npc_id)))
    }

    pub fn audit(&self, since: i64) -> Result<(Vec<AuditRecord>, i64), CortexError> {
        self.get::<Feed<AuditRecord>>(&format!("/v1/audit?since={since}"))
            .map(|r| (r.records, r.next_since))
    }

    pub fn delivered(&self, since: i64) -> Result<(Vec<(String, String)>, i64), CortexError> {
        self.get::<DeliveredResp>(&format!("/v1/delivered?since={since}"))
            .map(|r| (r.delivered, r.next_since))
    }

    pub fn actions(&self, since: i64) -> Result<(Vec<RemoteAction>, i64), CortexError> {
        self.get::<ActionsResp>(&format!("/v1/actions?since={since}"))
            .map(|r| (r.actions, r.next_since))
    }

    pub fn register_action(
        &self,
        name: &str,
        parameters: &HashMap<String, String>,
        min_implication: f64,
        broadcast: bool,
    ) -> Result<(), CortexError> {
        let body = serde_json::json!({
            "name": name,
            "parameters": parameters,
            "min_implication": min_implication,
            "broadcast": broadcast,
        });
        self.post::<serde_json::Value>("/v1/register_action", &body)
            .map(|_| ())
    }

    pub fn sync(
        &self,
        players: &[SyncPlayer],
        npcs: &[SyncNpc],
        world_state: Option<&HashMap<String, serde_json::Value>>,
    ) -> Result<serde_json::Value, CortexError> {
        let mut body = serde_json::json!({ "players": players, "npcs": npcs });
        if let Some(state) = world_state {
            body["world_state"] =
                serde_json::to_value(state).map_err(|e| CortexError::Json(e.to_string()))?;
        }
        self.post("/v1/sync", &body)
    }

    pub fn surroundings(&self, npc_id: &str, radius: f64) -> Result<Vec<NearbyPlace>, CortexError> {
        let path = format!(
            "/v1/surroundings?npc_id={}&radius={radius}",
            percent_encode(npc_id)
        );
        self.get::<PlacesResp>(&path).map(|r| r.places)
    }

    pub fn knowledge(
        &self,
        npc_id: &str,
        actor_id: Option<&str>,
        limit: Option<i64>,
    ) -> Result<(Vec<Observation>, HashMap<String, Acquaintance>), CortexError> {
        let mut path = format!("/v1/knowledge?npc_id={}", percent_encode(npc_id));
        if let Some(actor) = actor_id {
            path.push_str(&format!("&actor_id={}", percent_encode(actor)));
        }
        if let Some(limit) = limit {
            path.push_str(&format!("&limit={limit}"));
        }
        self.get::<KnowledgeResp>(&path)
            .map(|r| (r.history, r.acquaintances))
    }

    pub fn close(&self) -> Result<(), CortexError> {
        self.post::<serde_json::Value>("/v1/close", &serde_json::json!({}))
            .map(|_| ())
    }
}

fn parse_error_body(text: &str) -> (String, String) {
    let value: serde_json::Value = serde_json::from_str(text).unwrap_or_default();
    let name = value
        .get("error")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let detail = value
        .get("detail")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    (name, detail)
}
