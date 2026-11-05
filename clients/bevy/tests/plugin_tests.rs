//! Headless plugin checks: no renderer, no server, never hangs.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};

use bevy_app::{App, Last};
use bevy_ecs::prelude::{MessageReader, ResMut, Resource};
use npc_cortex_bevy::{
    AuditRequest, CancelRequest, CloseRequest, CortexBridge, CortexErrorRaised, EngageRequest,
    HealthRequest, KnowledgeRequest, MemoryRequest, NpcCortexPlugin, ObserveRequest,
    RegisterActionRequest, SpeakRequest, SurroundingsRequest, SyncRequest,
};

/// Unreachable server: frames still run, errors surface as messages.
#[test]
fn plugin_runs_headless_against_dead_server() {
    let mut app = App::new();
    app.add_plugins(NpcCortexPlugin {
        base_url: "http://127.0.0.1:9".to_string(),
    });
    app.world_mut()
        .write_message(SpeakRequest::say("n1", "p1", "hello?"));
    for _ in 0..5 {
        app.update();
    }
    // Dropping the App joins the worker; the test binary must exit.
}

/// The bridge resource is reachable and its helpers never panic.
#[test]
fn bridge_resource_helpers_are_total() {
    let mut app = App::new();
    app.add_plugins(NpcCortexPlugin {
        base_url: "http://127.0.0.1:9".to_string(),
    });
    app.update();
    let bridge = app.world().get_resource::<CortexBridge>().unwrap().clone();
    bridge.speak("tick", "n1", None, None);
    app.world_mut().write_message(SyncRequest::default());
    app.update();
    bridge.shutdown();
}

#[derive(Resource, Default)]
struct ErrorCount(usize);

fn count_errors(mut errors: MessageReader<CortexErrorRaised>, mut count: ResMut<ErrorCount>) {
    count.0 += errors.read().count();
}

/// Every request kind flows worker-side: against a dead server each
/// surfaces as `CortexErrorRaised` instead of hanging or panicking.
#[test]
fn every_request_kind_flows_without_server() {
    let mut app = App::new();
    app.add_plugins(NpcCortexPlugin {
        base_url: "http://127.0.0.1:9".to_string(),
    });
    app.init_resource::<ErrorCount>();
    app.add_systems(Last, count_errors);

    let world = app.world_mut();
    world.write_message(SpeakRequest::say("n1", "p1", "hello?"));
    world.write_message(SyncRequest::default());
    world.write_message(ObserveRequest {
        character_id: "n1".to_string(),
    });
    world.write_message(EngageRequest {
        request_id: 1,
        player_id: "p1".to_string(),
        name: "order".to_string(),
        parameters: HashMap::new(),
        duration: 0.0,
    });
    world.write_message(CancelRequest {
        handle: "no-such-handle".to_string(),
    });
    world.write_message(RegisterActionRequest {
        name: "order".to_string(),
        parameters: HashMap::new(),
        min_implication: 0.0,
        broadcast: false,
    });
    world.write_message(MemoryRequest {
        request_id: 2,
        npc_id: "n1".to_string(),
    });
    world.write_message(AuditRequest {
        request_id: 3,
        since: 0,
    });
    world.write_message(SurroundingsRequest {
        request_id: 4,
        npc_id: "n1".to_string(),
        radius: 10.0,
    });
    world.write_message(KnowledgeRequest {
        request_id: 5,
        npc_id: "n1".to_string(),
        actor_id: Some("p1".to_string()),
        limit: None,
    });
    world.write_message(HealthRequest { request_id: 6 });
    world.write_message(CloseRequest);

    for _ in 0..120 {
        app.update();
        if app.world().get_resource::<ErrorCount>().unwrap().0 > 0 {
            break;
        }
    }
    assert!(
        app.world().get_resource::<ErrorCount>().unwrap().0 > 0,
        "expected bridge errors against a dead server"
    );
}

fn error_count(app: &App) -> usize {
    app.world().get_resource::<ErrorCount>().unwrap().0
}

/// Run frames until the error count holds still (worker idle), or a cap.
fn settled_count(app: &mut App) -> usize {
    let mut last = usize::MAX;
    let mut stable = 0;
    for _ in 0..300 {
        app.update();
        let now = error_count(app);
        if now == last {
            stable += 1;
            if stable >= 10 {
                return now;
            }
        } else {
            stable = 0;
            last = now;
        }
    }
    last
}

/// After `Close`, frames stay quiet but queries still round-trip:
/// a later `MemoryRequest` surfaces a fresh error instead of
/// vanishing into an exited worker.
#[test]
fn close_keeps_worker_up_for_queries() {
    let mut app = App::new();
    app.add_plugins(NpcCortexPlugin {
        base_url: "http://127.0.0.1:9".to_string(),
    });
    app.init_resource::<ErrorCount>();
    app.add_systems(Last, count_errors);

    app.world_mut().write_message(CloseRequest);
    let before = settled_count(&mut app);
    assert!(before > 0, "expected the close itself to error");

    app.world_mut().write_message(MemoryRequest {
        request_id: 7,
        npc_id: "n1".to_string(),
    });
    for _ in 0..300 {
        app.update();
        if error_count(&app) > before {
            return;
        }
    }
    panic!("post-close query never round-tripped (worker exited?)");
}

// ---------------------------------------------------------------------------
// scripted frame-parity run against a mock bridge (std only)
// ---------------------------------------------------------------------------

struct MockBridge {
    port: u16,
    paths: Arc<Mutex<Vec<String>>>,
    stop: Arc<AtomicBool>,
}

impl Drop for MockBridge {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        let _ = TcpStream::connect(format!("127.0.0.1:{}", self.port));
    }
}

fn read_request(stream: &mut TcpStream) -> Option<(String, usize)> {
    let mut head = Vec::new();
    let mut byte = [0u8; 1];
    while head.len() < 8192 {
        match stream.read(&mut byte) {
            Ok(0) => return None,
            Ok(_) => head.push(byte[0]),
            Err(_) => return None,
        }
        if head.ends_with(b"\r\n\r\n") {
            break;
        }
    }
    let head = String::from_utf8_lossy(&head).into_owned();
    let mut len = 0usize;
    for line in head.lines().skip(1) {
        if let Some(v) = line.strip_prefix("Content-Length:") {
            len = v.trim().parse().unwrap_or(0);
        }
        if let Some(v) = line.strip_prefix("content-length:") {
            len = v.trim().parse().unwrap_or(0);
        }
    }
    let path = head
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .unwrap_or("/")
        .to_string();
    let mut body = vec![0u8; len];
    if len > 0 {
        stream.read_exact(&mut body).ok()?;
    }
    Some((path, len))
}

fn mock_body(path: &str) -> String {
    if let Some(q) = path.strip_prefix("/v1/delivered") {
        let since: i64 = q
            .strip_prefix("?since=")
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        return format!("{{\"delivered\":[],\"next_since\":{}}}", since + 1);
    }
    if let Some(q) = path.strip_prefix("/v1/actions") {
        let since: i64 = q
            .strip_prefix("?since=")
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        return format!("{{\"actions\":[],\"next_since\":{}}}", since + 1);
    }
    if path == "/v1/pump" {
        return "{\"resolved\":0}".to_string();
    }
    "{}".to_string()
}

fn start_mock() -> MockBridge {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock bridge");
    let port = listener.local_addr().expect("mock port").port();
    let paths = Arc::new(Mutex::new(Vec::new()));
    let stop = Arc::new(AtomicBool::new(false));
    let worker_paths = paths.clone();
    let worker_stop = stop.clone();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            if worker_stop.load(Ordering::SeqCst) {
                break;
            }
            let mut stream = match stream {
                Ok(s) => s,
                Err(_) => continue,
            };
            let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
            loop {
                let Some((path, _)) = read_request(&mut stream) else {
                    break;
                };
                worker_paths.lock().expect("paths lock").push(path.clone());
                let body = mock_body(&path);
                let resp = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: keep-alive\r\n\r\n{}",
                    body.len(),
                    body
                );
                if stream.write_all(resp.as_bytes()).is_err() {
                    break;
                }
            }
        }
    });
    MockBridge { port, paths, stop }
}

impl MockBridge {
    fn pump_count(&self) -> usize {
        self.paths
            .lock()
            .expect("paths lock")
            .iter()
            .filter(|p| p.as_str() == "/v1/pump")
            .count()
    }
}

/// Scripted N-step run: one pump per frame, per-frame order
/// `pump -> delivered -> actions`, cursors advancing, zero errors.
#[test]
fn pump_count_matches_frame_count_over_scripted_run() {
    let mock = start_mock();
    let mut app = App::new();
    app.add_plugins(NpcCortexPlugin {
        base_url: format!("http://127.0.0.1:{}", mock.port),
    });
    app.init_resource::<ErrorCount>();
    app.add_systems(Last, count_errors);

    for i in 1..=5usize {
        app.update();
        let deadline = Instant::now() + Duration::from_secs(10);
        while mock.pump_count() < i {
            assert!(Instant::now() < deadline, "worker stalled on frame {i}");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    // Let the final polls land, then freeze the record.
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let n = mock.paths.lock().expect("paths lock").len();
        if n >= 15 || Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let paths = mock.paths.lock().expect("paths lock").clone();
    assert_eq!(mock.pump_count(), 5, "pumps != frames: {paths:?}");
    assert_eq!(paths.len(), 15, "unexpected extra calls: {paths:?}");
    let bare: Vec<&str> = paths
        .iter()
        .map(|p| p.split('?').next().unwrap_or("/"))
        .collect();
    for frame in bare.chunks(3) {
        assert_eq!(frame, ["/v1/pump", "/v1/delivered", "/v1/actions"]);
    }
    let sinces: Vec<&str> = paths
        .iter()
        .filter(|p| p.starts_with("/v1/delivered"))
        .map(String::as_str)
        .collect();
    assert_eq!(
        sinces,
        [
            "/v1/delivered?since=0",
            "/v1/delivered?since=1",
            "/v1/delivered?since=2",
            "/v1/delivered?since=3",
            "/v1/delivered?since=4",
        ]
    );
    assert_eq!(error_count(&app), 0, "clean run must stay error-free");
}
