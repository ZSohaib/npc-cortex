"""Asyncio adapter tests."""

import asyncio
import time

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.adapters.asyncio_adapter import attach_asyncio


def test_asyncio_pump_resolves():
    async def main():
        _, rt = make_world(Scripted(answer(speech="hi")))
        pump = attach_asyncio(rt, fps=60.0)
        try:
            rt.submit(m.Event(kind="tick", npc_id="n1"))
            end = time.monotonic() + 5.0
            while not rt.gateway.delivered and time.monotonic() < end:
                await asyncio.sleep(0.01)
            assert rt.gateway.delivered == [("p1", "hi")]
        finally:
            await pump.stop()
    asyncio.run(main())


def test_asyncio_stop_is_idempotent():
    async def main():
        _, rt = make_world(Scripted(answer()))
        pump = attach_asyncio(rt, fps=120.0)
        await pump.stop()
        await pump.stop()
    asyncio.run(main())
