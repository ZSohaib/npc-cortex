"""Rust protocol conformance: mapping + wire flow the Rust client performs."""

import time

from conftest import Scripted, answer, make_world
from npc_cortex.adapters import rust
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer


def test_rust_vec3_sync_submit_pump_delivers():
    _, rt = make_world(Scripted(answer(speech="systems nominal")))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        pos = rust.vec_to_position([7.0, 1.0, -2.0])  # Bevy Vec3
        client.sync(players=[{"id": "p1", "position": list(pos), "horizon": 50.0}],
                    npcs=[{"id": "n1", "position": [8.0, 1.0, -2.0],
                            "horizon": 50.0}])
        client.submit("direct_message", "n1", speaker_id="p1", text="status?")
        resolved, end = 0, time.monotonic() + 5.0
        while not resolved and time.monotonic() < end:
            resolved += client.pump()
        assert resolved == 1
        assert client.delivered()["delivered"] == [("p1", "systems nominal")]
        back = rust.position_to_vec3(rt.scenario.players[0].position)
        assert back == (7.0, 1.0, -2.0)
        out = client.knowledge("n1")
        assert set(out) == {"history", "acquaintances"}
    finally:
        srv.stop()
        rt.close()


def test_rust_cancel_unknown_is_inert_and_close_maps():
    import npc_cortex as m

    _, rt = make_world(Scripted(answer()))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        client.cancel("engagement-7")
        client.close()
        try:
            client.pump()
            raise AssertionError("expected Closed")
        except m.Closed:
            pass
    finally:
        srv.stop()
