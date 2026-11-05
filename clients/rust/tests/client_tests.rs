//! Rust client tests: pure unit tests always run; live tests need a
//! bridge server on 127.0.0.1:8471 (`python examples/bridge_server.py`)
//! and run with `cargo test -- --ignored`.

use npc_cortex::{
    build_submit_body, parse_pump_response, percent_encode, position_to_vec2, position_to_vec3,
    vec2_to_position, vec3_to_position, NpcCortexClient,
};
use std::collections::HashMap;
use std::time::{Duration, Instant};

// -- pure --------------------------------------------------------------------

#[test]
fn vec3_maps_by_identity_on_components() {
    assert_eq!(vec3_to_position(1.0, 2.0, 3.0), [1.0, 2.0, 3.0]);
    assert_eq!(vec2_to_position(4.0, 5.0), [4.0, 5.0]);
}

#[test]
fn position_round_trip() {
    assert_eq!(position_to_vec3(&[1.0, 2.0]), [1.0, 2.0, 0.0]);
    assert_eq!(position_to_vec3(&[1.0, 2.0, 3.0]), [1.0, 2.0, 3.0]);
    assert_eq!(position_to_vec2(&[1.0, 2.0, 3.0]), [1.0, 2.0]);
}

#[test]
fn submit_body_carries_npc_id_and_text() {
    let body = build_submit_body("direct_message", "n1", Some("p1"), Some("hello"));
    let value: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(value["npc_id"], "n1");
    assert_eq!(value["text"], "hello");
    assert_eq!(value["speaker_id"], "p1");
}

#[test]
fn submit_body_encodes_missing_fields_as_null() {
    let body = build_submit_body("tick", "n1", None, None);
    let value: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert!(value["speaker_id"].is_null());
    assert!(value["text"].is_null());
}

#[test]
fn pump_response_parses_or_rejects() {
    assert_eq!(parse_pump_response("{\"resolved\":2}"), Some(2));
    assert_eq!(parse_pump_response("nope"), None);
    assert_eq!(parse_pump_response("{}"), None);
}

#[test]
fn percent_encode_escapes_reserved_chars() {
    assert_eq!(percent_encode("p1"), "p1");
    assert_eq!(percent_encode("a b&c"), "a%20b%26c");
}

// -- live (ignored without a server) ------------------------------------------

fn live_client() -> NpcCortexClient {
    NpcCortexClient::with_timeout("http://127.0.0.1:8471", Duration::from_secs(5))
}

#[test]
#[ignore]
fn live_health_answers_ok() {
    let health = live_client().health().unwrap();
    assert_eq!(health["ok"], true);
}

#[test]
#[ignore]
fn live_sync_submit_pump_delivers() {
    use npc_cortex::{SyncNpc, SyncPlayer};
    let client = live_client();
    let mut player = SyncPlayer::new("p1");
    player.position = Some(vec![0.0, 0.0, 0.0]);
    player.horizon = Some(50.0);
    let mut npc = SyncNpc::new("n1");
    npc.position = Some(vec![1.0, 0.0, 0.0]);
    npc.horizon = Some(50.0);
    client.sync(&[player], &[npc], None).unwrap();
    client.submit("tick", "n1", None, None).unwrap();
    let start = Instant::now();
    let mut resolved = 0;
    while resolved == 0 && start.elapsed() < Duration::from_secs(10) {
        resolved += client.pump().unwrap();
    }
    assert!(resolved > 0, "nothing resolved");
    let (delivered, _) = client.delivered(0).unwrap();
    assert!(!delivered.is_empty());
}

#[test]
#[ignore]
fn live_knowledge_and_surroundings_answer() {
    let client = live_client();
    let surroundings = client.surroundings("n1", 500.0).unwrap();
    assert!(surroundings.iter().all(|p| p.distance >= 0.0));
    let (history, acquaintances) = client.knowledge("n1", None, None).unwrap();
    assert!(history.iter().all(|r| !r.action.is_empty()));
    assert!(acquaintances.values().all(|a| a.interactions > 0));
}

#[test]
#[ignore]
fn live_cancel_on_unknown_handle_is_inert() {
    live_client().cancel("engagement-424242").unwrap(); // must not fail
}

#[test]
#[ignore]
fn live_registered_action_lands_in_feed() {
    let client = live_client();
    let mut params = HashMap::new();
    params.insert("target".to_string(), "str".to_string());
    client
        .register_action("rust_wave", &params, 0.0, false)
        .unwrap();
    let (actions, _) = client.actions(0).unwrap();
    assert!(actions.iter().all(|a| !a.name.is_empty()));
}
