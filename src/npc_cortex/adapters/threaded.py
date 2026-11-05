"""Background-thread adapter: pump at a fixed rate without engine hooks.

Use when the engine exposes no per-frame callback, or for headless
services and tests. Handlers, gateway writes, and observation appends
(all spec 3.3 effects) run on the adapter's thread, so handlers must be
thread-safe with respect to the engine, exactly as with any background
pumper.
"""

from __future__ import annotations

import threading
import time

from ..models import Closed

__all__ = ["ThreadedPump", "attach_threaded"]


class ThreadedPump:
    """Pumps ``runtime`` ``fps`` times per second on a daemon thread."""

    name = "threaded"

    def __init__(self, runtime, fps: float = 60.0) -> None:
        if not float(fps) > 0.0:
            raise ValueError("fps must be positive, got %r" % (fps,))
        self.runtime = runtime
        self.fps = float(fps)
        self.ticks = 0
        self.resolved = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="npc-cortex-pump", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            start = time.monotonic()
            try:
                n = self.runtime.pump()
            except Closed:
                return
            except Exception:
                return  # pragma: no cover - pump() only raises Closed
            self.ticks += 1
            self.resolved += n
            self._stop.wait(max(0.0, interval - (time.monotonic() - start)))

    def stop(self, timeout: float = 2.0) -> None:
        """Stop pumping. Idempotent."""
        self._stop.set()
        self._thread.join(timeout=timeout)

    # EngineAdapter-shaped alias --------------------------------------

    def detach(self) -> None:  # noqa: D102
        self.stop()

    def attach(self, runtime, fps: float = 60.0) -> "ThreadedPump":  # noqa: D102
        return attach_threaded(runtime, fps=fps)


def attach_threaded(runtime, fps: float = 60.0) -> ThreadedPump:
    """Start a background pumper; the return value is the detach handle."""
    return ThreadedPump(runtime, fps=fps)
