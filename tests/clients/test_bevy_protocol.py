"""Bevy protocol conformance: the wire flow the Bevy worker performs."""

import time
from pathlib import Path

from conftest import Scripted, answer, make_world
from npc_cortex.adapters import rust
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer

BEVY = Path(__file__).resolve().parent.parent.parent / "clients" / "bevy"


def test_bevy_crate_ships_plugin_and_lock():
    assert (BEVY / "Cargo.toml").is_file()
    assert (BEVY / "Cargo.lock").is_file()
    assert (BEVY / "src" / "lib.rs").is_file()
    assert (BEVY / "tests" / "plugin_tests.rs").is_file()
    assert (BEVY / "README.md").is_file()
    src = (BEVY / "src" / "lib.rs").read_text()
    for symbol in ("NpcCortexPlugin", "SpeakRequest", "SyncRequest",
                   "ObserveRequest", "EngageRequest", "CancelRequest",
                   "RegisterActionRequest", "MemoryRequest", "AuditRequest",
                   "SurroundingsRequest", "KnowledgeRequest",
                   "HealthRequest", "CloseRequest", "NpcSpeech",
                   "NpcObserved", "NpcActionRaised", "EngagementOpened",
                   "MemoryReceived", "AuditReceived", "SurroundingsReceived",
                   "KnowledgeReceived", "HealthReceived", "CortexErrorRaised",
                   "to_cortex_vec3", "from_cortex_position"):
        assert symbol in src, symbol


def test_bevy_worker_flow_sync_submit_pump_poll():
    # One worker tick: sync transforms -> submit speech -> pump ->
    # poll delivered + actions with cursors.
    _, rt = make_world(Scripted(answer(speech="ready, captain")))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        pos = rust.vec_to_position([7.0, 1.0, -2.0])  # Bevy Vec3
        client.sync(players=[{"id": "p1", "position": list(pos),
                              "horizon": 50.0}],
                    npcs=[{"id": "n1", "position": [8.0, 1.0, -2.0],
                            "horizon": 50.0}])
        client.submit("direct_message", "n1", speaker_id="p1",
                      text="status?")
        resolved, end = 0, time.monotonic() + 5.0
        while not resolved and time.monotonic() < end:
            resolved += client.pump()
        assert resolved == 1
        out = client.delivered(0)
        assert out["delivered"] == [("p1", "ready, captain")]
        assert out["next_since"] > 0
        acts = client.actions(0)
        assert acts["actions"] == [] and acts["next_since"] >= 0
        back = rust.position_to_vec3(rt.scenario.players[0].position)
        assert back == (7.0, 1.0, -2.0)
    finally:
        srv.stop()
        rt.close()


def test_bevy_observe_round_trip_and_close_maps():
    import npc_cortex as m

    _, rt = make_world(Scripted(answer()))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        assert client.observations("ghost") == []
        client.cancel("bevy-no-such-handle")
        client.close()
        try:
            client.pump()
            raise AssertionError("expected Closed")
        except m.Closed:
            pass
    finally:
        srv.stop()
