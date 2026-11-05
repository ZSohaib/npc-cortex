"""Loop adapter tests (generic frame-loop engines)."""

import time

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.adapters.loop import attach_loop, attach_register


def test_n_ticks_pump_n_times():
    calls = []
    _, rt = make_world(Scripted(answer()))
    pump = attach_loop(rt)
    for _ in range(5):
        calls.append(pump.tick())
    assert pump.ticks == 5


def test_tick_resolves_submitted_event():
    _, rt = make_world(Scripted(answer(speech="hi")))
    pump = attach_loop(rt)
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    for _ in range(500):  # provider answers on a background thread
        pump.tick()
        if rt.gateway.delivered:
            break
        time.sleep(0.005)
    assert rt.gateway.delivered == [("p1", "hi")]
    assert pump.resolved == 1


def test_tick_after_close_is_inert():
    _, rt = make_world(Scripted(answer()))
    pump = attach_loop(rt)
    rt.close()
    assert pump.tick() == 0
    assert pump.tick() == 0


def test_register_wires_engine_callback_list():
    callbacks = []
    _, rt = make_world(Scripted(answer(speech="hi")))
    pump = attach_register(rt, callbacks.append, callbacks.remove)
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    for _ in range(500):  # engine frames until the provider answers
        for cb in list(callbacks):
            cb()
        if rt.gateway.delivered:
            break
        time.sleep(0.005)
    assert rt.gateway.delivered == [("p1", "hi")]
    pump.detach()
    assert callbacks == []
    pump.detach()  # idempotent
