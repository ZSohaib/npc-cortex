"""Panda3D adapter tests.

Uses a duck-typed TaskManager fake matching the Panda3D interface
(`add`/`step`/`getAllTasks`/`remove`, `Task.cont`/`Task.done`); when a
real Panda3D is installed the same tests run against it too.
"""

import sys
import time
import types

import pytest

import npc_cortex as m
from conftest import Scripted, answer, make_world


class FakeTask:
    cont = "cont"
    done = "done"


class FakeTaskManager:
    def __init__(self):
        self._tasks = []

    def add(self, fn, name):
        task = types.SimpleNamespace(fn=fn, name=name)
        self._tasks.append(task)
        return task

    def getAllTasks(self):
        return list(self._tasks)

    def remove(self, task):
        self._tasks = [t for t in self._tasks if t is not task]

    def step(self):
        for task in list(self._tasks):
            if task.fn(task) == FakeTask.done:
                self.remove(task)


def _install_fake_direct():
    task_mod = types.ModuleType("direct.task.Task")
    task_mod.Task = FakeTask
    task_pkg = types.ModuleType("direct.task")
    task_pkg.Task = task_mod
    direct_pkg = types.ModuleType("direct")
    direct_pkg.task = task_pkg
    sys.modules.setdefault("direct", direct_pkg)
    sys.modules.setdefault("direct.task", task_pkg)
    sys.modules.setdefault("direct.task.Task", task_mod)


try:
    import direct.task.Task  # noqa: F401
    _HAVE_PANDA = True
except ImportError:
    _HAVE_PANDA = False
    _install_fake_direct()


def _task_manager():
    if _HAVE_PANDA:
        from direct.task.Task import TaskManager
        return TaskManager()
    return FakeTaskManager()


def test_n_steps_pump_n_times():
    from npc_cortex.adapters.panda3d import attach
    _, rt = make_world(Scripted(answer()))
    tm = _task_manager()
    attach(rt, tm)
    for _ in range(4):
        tm.step()
    assert rt._epoch == 4


def test_attached_task_resolves_event():
    from npc_cortex.adapters.panda3d import attach
    _, rt = make_world(Scripted(answer(speech="stepped")))
    tm = _task_manager()
    attach(rt, tm)
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    end = time.monotonic() + 5.0
    while not rt.gateway.delivered and time.monotonic() < end:
        tm.step()
        time.sleep(0.01)
    assert rt.gateway.delivered == [("p1", "stepped")]


def test_top_level_attach_is_panda_attach():
    _, rt = make_world(Scripted(answer()))
    tm = _task_manager()
    m.attach(rt, tm)
    tm.step()
    assert rt._epoch == 1


def test_stepping_after_close_does_not_raise():
    from npc_cortex.adapters.panda3d import attach
    _, rt = make_world(Scripted(answer()))
    tm = _task_manager()
    attach(rt, tm)
    tm.step()
    rt.close()
    for _ in range(3):
        tm.step()  # must not raise
