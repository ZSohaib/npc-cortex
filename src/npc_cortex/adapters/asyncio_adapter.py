"""Asyncio adapter: pump from an event loop (servers, tools, async games).

The blocking ``runtime.pump()`` runs in the loop's default executor so
the event loop never stalls, mirroring the non-blocking guarantee the
core gives frame loops.
"""

from __future__ import annotations

import asyncio

from ..models import Closed

__all__ = ["AsyncioPump", "attach_asyncio"]


class AsyncioPump:
    """Pumps ``runtime`` ``fps`` times per second as an asyncio task."""

    name = "asyncio"

    def __init__(self, runtime, loop=None, fps: float = 60.0) -> None:
        if not float(fps) > 0.0:
            raise ValueError("fps must be positive, got %r" % (fps,))
        self.runtime = runtime
        self.fps = float(fps)
        self.ticks = 0
        self.resolved = 0
        self._loop = loop or asyncio.get_running_loop()
        self._stop = False
        self._task = self._loop.create_task(self._run())

    async def _run(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop:
            try:
                n = await self._loop.run_in_executor(None, self.runtime.pump)
            except Closed:
                return
            self.ticks += 1
            self.resolved += n
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        """Stop pumping. Idempotent."""
        self._stop = True
        if self._task is not None:
            task, self._task = self._task, None
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

    def detach(self) -> None:  # noqa: D102
        self._stop = True
        if self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def attach(self, runtime, loop=None, fps: float = 60.0) -> "AsyncioPump":  # noqa: D102
        return attach_asyncio(runtime, loop=loop, fps=fps)


def attach_asyncio(runtime, loop=None, fps: float = 60.0) -> AsyncioPump:
    """Start an asyncio pumper; the return value is the detach handle."""
    return AsyncioPump(runtime, loop=loop, fps=fps)
