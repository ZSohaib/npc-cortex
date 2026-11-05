"""Run a BridgeServer for Unity/Unreal/Godot native clients.

Usage:
    python examples/bridge_server.py [--port 8471]

Then point the engine client at http://127.0.0.1:8471 and follow
docs/PROTOCOL.md (sync -> submit -> pump -> poll actions/delivered).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from npc_cortex import (ActionRegistry, AuditLog, Gateway, NPC, Player,
                        Runtime, Scenario)
from npc_cortex.server import BridgeServer


class EchoProvider:
    def complete(self, prompt):
        return json.dumps({"speech": "hello from the bridge!",
                           "emotion": "neutral", "actions": [], "memory": []})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8471)
    args = parser.parse_args()
    scenario = Scenario(
        players=[Player(id="p1", role="player", position=(0.0, 0.0, 0.0),
                        horizon=50.0, online=True)],
        npcs=[NPC(id="n1", position=(1.0, 0.0, 0.0), horizon=50.0,
                  implication=0.5)],
        world_state={},
    )
    runtime = Runtime(scenario, EchoProvider(), ActionRegistry(), Gateway(),
                      AuditLog())
    server = BridgeServer(runtime, port=args.port)
    print("npc-cortex serving at", server.start(), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
        runtime.close()


if __name__ == "__main__":
    main()
