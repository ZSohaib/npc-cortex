"""Panda3D adapter: the original ``attach()`` (spec 3.12)."""

from __future__ import annotations

from ..models import Closed

__all__ = ["attach"]


def attach(runtime, task_mgr) -> None:
    """Pump ``runtime`` once per ``task_mgr.step()``, headless.

    N calls to ``task_mgr.step()`` invoke ``runtime.pump()`` exactly N
    times. After ``runtime.close()`` the task retires silently and
    ``task_mgr.step()`` does not raise.
    """
    from direct.task.Task import Task

    def _pump_task(task):
        if getattr(runtime, "_closed", False):
            return Task.done
        try:
            runtime.pump()
        except Closed:
            return Task.done
        return Task.cont

    task_mgr.add(_pump_task, "npc_cortex-pump")
