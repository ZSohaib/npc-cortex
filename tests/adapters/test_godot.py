"""Godot adapter tests (duck-typed nodes; no engine needed)."""

from types import SimpleNamespace

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.adapters.godot import GodotAdapter, position_to_vec, vec_to_position


def test_vec_mapping_round_trip():
    assert vec_to_position(SimpleNamespace(x=1, y=2, z=3)) == (1.0, 2.0, 3.0)
    assert vec_to_position(SimpleNamespace(x=1, y=2)) == (1.0, 2.0)
    assert vec_to_position((1, 2)) == (1.0, 2.0)
    assert position_to_vec((1.0, 2.0), vec3=True) == (1.0, 2.0, 0.0)
    assert position_to_vec((1.0, 2.0, 3.0), vec3=False) == (1.0, 2.0)


def test_process_pumps_like_frame_loop():
    import time
    _, rt = make_world(Scripted(answer(speech="a"), answer(speech="b")))
    bridge = GodotAdapter(rt)
    rt.submit(m.Event(kind="tick", npc_id="n1", text="one"))
    bridge.process()
    assert bridge.ticks == 1
    rt.submit(m.Event(kind="tick", npc_id="n1", text="two"))
    for _ in range(500):
        bridge.process()
        if len(rt.gateway.delivered) == 2:
            break
        time.sleep(0.005)
    assert [t for _, t in rt.gateway.delivered] == ["a", "b"]
    assert bridge.ticks >= 2  # the pump stayed alive across events


def test_sync_node_updates_position_and_online():
    scenario, rt = make_world(Scripted(answer()))
    bridge = GodotAdapter(rt)
    assert bridge.sync_node("p1", SimpleNamespace(x=9, y=8, z=7)) is True
    assert scenario.players[0].position == (9.0, 8.0, 7.0)
    assert bridge.sync_node("p1", (0, 0), online=False) is True
    assert scenario.players[0].online is False
    assert bridge.sync_node("ghost", (0, 0)) is False
    assert bridge.read_node("p1") == (0.0, 0.0)
    assert bridge.read_node("ghost") is None


def test_process_after_close_is_inert():
    _, rt = make_world(Scripted(answer()))
    bridge = GodotAdapter(rt)
    rt.close()
    assert bridge.process() == 0
