"""Unity protocol conformance: mapping + wire flow the C# client performs."""

import time

from conftest import Scripted, answer, make_world
from npc_cortex.adapters import unity
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer


def _live(provider):
    _, rt = make_world(provider)
    srv = BridgeServer(rt)
    return srv, RemoteBridge(srv.start()), rt


def test_unity_vec3_sync_submit_pump_delivers():
    srv, client, rt = _live(Scripted(answer(speech="for the king")))
    try:
        pos = unity.vec_to_position((10.0, 1.5, -3.0))  # Vector3(x, y, z)
        client.sync(players=[{"id": "p1", "position": list(pos), "horizon": 50.0}],
                    npcs=[{"id": "n1", "position": [11.0, 1.5, -3.0],
                            "horizon": 50.0}])
        client.submit("direct_message", "n1", speaker_id="p1", text="hail")
        resolved, end = 0, time.monotonic() + 5.0
        while not resolved and time.monotonic() < end:
            resolved += client.pump()
        assert resolved == 1
        assert client.delivered()["delivered"] == [("p1", "for the king")]
        back = unity.position_to_vec3(rt.scenario.players[0].position)
        assert back == (10.0, 1.5, -3.0)
    finally:
        srv.stop()
        rt.close()


def test_unity_cancel_unknown_is_inert_and_close_maps():
    import npc_cortex as m

    srv, client, rt = _live(Scripted(answer()))
    try:
        client.cancel("engagement-9")
        client.close()
        try:
            client.pump()
            raise AssertionError("expected Closed")
        except m.Closed:
            pass
    finally:
        srv.stop()
