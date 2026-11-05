"""Threaded adapter tests."""

import time

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.adapters.threaded import attach_threaded


def test_background_pump_resolves_without_engine_ticks():
    _, rt = make_world(Scripted(answer(speech="hi")))
    pump = attach_threaded(rt, fps=60.0)
    try:
        rt.submit(m.Event(kind="tick", npc_id="n1"))
        end = time.monotonic() + 5.0
        while not rt.gateway.delivered and time.monotonic() < end:
            time.sleep(0.01)
        assert rt.gateway.delivered == [("p1", "hi")]
        assert pump.ticks >= 1
    finally:
        pump.stop()


def test_stop_is_idempotent_and_prompt():
    _, rt = make_world(Scripted(answer()))
    pump = attach_threaded(rt, fps=200.0)
    pump.stop()
    pump.stop()
    pump.detach()
