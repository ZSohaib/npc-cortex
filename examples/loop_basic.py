"""Minimal in-process game loop (any engine): tick a FramePump per frame."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from npc_cortex import (ActionRegistry, AuditLog, Event, Gateway, NPC, Player,
                        Runtime, Scenario)
from npc_cortex.adapters.loop import attach_loop


class EchoProvider:
    def complete(self, prompt):
        return json.dumps({"speech": "hello, traveler!", "emotion": "kind",
                           "actions": [{"name": "wave", "parameters": {}}],
                           "memory": []})


def main():
    scenario = Scenario(
        players=[Player(id="p1", role="scout", position=(0.0, 0.0),
                        horizon=50.0, online=True)],
        npcs=[NPC(id="n1", position=(1.0, 0.0), horizon=50.0, implication=0.5)],
        world_state={},
    )
    registry = ActionRegistry()
    registry.register("wave", {}, 0.0,
                      lambda s, n, p: print("[game] %s waves" % n.id))
    gateway = Gateway()
    runtime = Runtime(scenario, EchoProvider(), registry, gateway, AuditLog())
    pump = attach_loop(runtime)

    runtime.submit(Event(kind="direct_message", npc_id="n1",
                         speaker_id="p1", text="hi"))
    for frame in range(120):  # ~2s at 60fps
        pump.tick()
        time.sleep(1 / 60)
    print("delivered:", gateway.delivered)
    print("audit:", [r["kind"] for r in runtime.audit.records])


if __name__ == "__main__":
    main()
