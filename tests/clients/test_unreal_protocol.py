"""Unreal protocol conformance: mapping + wire flow the C++ client performs."""

import time

from conftest import Scripted, answer, make_world
from npc_cortex.adapters import unreal
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer


def test_unreal_fvector_sync_submit_pump_delivers():
    _, rt = make_world(Scripted(answer(speech="for the horde")))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        pos = unreal.vec_to_position((100.0, 200.0, 50.0))  # FVector cm
        client.sync(players=[{"id": "p1", "position": list(pos),
                              "horizon": 5000.0}],
                    npcs=[{"id": "n1", "position": [150.0, 200.0, 50.0],
                            "horizon": 5000.0}])
        client.submit("direct_message", "n1", speaker_id="p1", text="lok'tar")
        resolved, end = 0, time.monotonic() + 5.0
        while not resolved and time.monotonic() < end:
            resolved += client.pump()
        assert resolved == 1
        assert client.delivered()["delivered"] == [("p1", "for the horde")]
        back = unreal.position_to_fvector(rt.scenario.npcs[0].position)
        assert back == (150.0, 200.0, 50.0)
        obs = client.observations("p1")
        assert obs == [] or set(obs[0]) == {"handle", "actor_id", "action", "phase"}
    finally:
        srv.stop()
        rt.close()


def test_unreal_cancel_unknown_is_inert():
    _, rt = make_world(Scripted(answer()))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        client.cancel("engagement-123")
        client.pump()  # nothing submitted: resolves 0
    finally:
        srv.stop()
        rt.close()
