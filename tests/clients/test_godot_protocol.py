"""Godot protocol conformance: mapping + wire flow the GDScript client performs."""

import time

from conftest import Scripted, answer, make_world
from npc_cortex.adapters.godot import vec_to_position
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer


def test_godot_vec2_sync_submit_pump_delivers():
    _, rt = make_world(Scripted(answer(speech="hola")))
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        pos = vec_to_position((320.0, 240.0))  # Vector2(x, y)
        client.sync(players=[{"id": "p1", "position": list(pos), "horizon": 500.0}],
                    npcs=[{"id": "n1", "position": [340.0, 240.0],
                            "horizon": 500.0}])
        client.submit("tick", "n1")
        resolved, end = 0, time.monotonic() + 5.0
        while not resolved and time.monotonic() < end:
            resolved += client.pump()
        assert resolved == 1
        assert client.delivered()["delivered"] == [("p1", "hola")]
    finally:
        srv.stop()
        rt.close()


def test_godot_cancel_unknown_is_inert_and_obs_keys_exact():
    _, rt = make_world(Scripted(answer(actions=[("dance", {})])))
    rt.registry.register("dance", {}, 0.0, lambda s, n, p: None)
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        client.cancel("engagement-1")
        client.submit("tick", "n1")
        end = time.monotonic() + 5.0
        while not client.pump() and time.monotonic() < end:
            pass
        obs = client.observations("p1")
        assert len(obs) == 1
        assert set(obs[0]) == {"handle", "actor_id", "action", "phase"}
        assert obs[0]["phase"] == "completed"
    finally:
        srv.stop()
        rt.close()
