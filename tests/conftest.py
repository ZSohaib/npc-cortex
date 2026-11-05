"""Shared fixtures: path setup plus tiny scripted providers."""

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import npc_cortex as m  # noqa: E402


def answer(speech=None, emotion=None, actions=(), memory=()):
    return json.dumps(
        {
            "speech": speech,
            "emotion": emotion,
            "actions": [{"name": n, "parameters": p} for n, p in actions],
            "memory": list(memory),
        }
    )


class Scripted:
    def __init__(self, *answers, delay=0.0):
        self._answers = list(answers) or [None]
        self._delay = delay
        self._lock = threading.Lock()
        self.calls = 0

    def complete(self, prompt):
        with self._lock:
            index = self.calls
            self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        item = self._answers[min(index, len(self._answers) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


def make_world(provider, players=None, npcs=None, **kwargs):
    if players is None:
        players = [m.Player(id="p1", role="scout", position=(0.0, 0.0),
                            horizon=50.0, online=True)]
    if npcs is None:
        npcs = [m.NPC(id="n1", position=(1.0, 0.0), horizon=50.0, implication=0.5)]
    scenario = m.Scenario(players=players, npcs=npcs, world_state={})
    runtime = m.Runtime(scenario, provider, m.ActionRegistry(), m.Gateway(),
                        m.AuditLog(), **kwargs)
    return scenario, runtime


def drain(runtime, expected, timeout=10.0):
    total = 0
    end = time.monotonic() + timeout
    while total < expected and time.monotonic() < end:
        total += runtime.pump()
        time.sleep(0.005)
    assert total == expected, "resolved %d of %d" % (total, expected)
