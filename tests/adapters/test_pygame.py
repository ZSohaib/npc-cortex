"""Pygame adapter tests (duck-typed sprites; pygame never imported)."""

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.adapters.pygame_adapter import PygameAdapter


def test_tick_pumps_once_per_frame():
    import time
    _, rt = make_world(Scripted(answer(speech="hi")))
    bridge = PygameAdapter(rt)
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    for _ in range(5):
        bridge.tick()  # game loop frames
    assert bridge.ticks == 5
    for _ in range(500):  # frames until the provider answers
        bridge.tick()
        if rt.gateway.delivered:
            break
        time.sleep(0.005)
    assert rt.gateway.delivered == [("p1", "hi")]
    assert bridge.pump.resolved == 1


def test_sync_sprite_round_trip():
    scenario, rt = make_world(Scripted(answer()))
    bridge = PygameAdapter(rt)
    assert bridge.sync_sprite("n1", (320, 240)) is True
    assert scenario.npcs[0].position == (320.0, 240.0)
    assert bridge.read_sprite("n1") == (320.0, 240.0)
    assert bridge.sync_sprite("ghost", (0, 0)) is False
    assert bridge.read_sprite("ghost") is None


def test_tick_after_close_is_inert():
    _, rt = make_world(Scripted(answer()))
    bridge = PygameAdapter(rt)
    rt.close()
    assert bridge.tick() == 0
