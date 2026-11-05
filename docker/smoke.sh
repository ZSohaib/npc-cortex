#!/bin/sh
# Smoke test: every engine adapter + bridge + clients + game, isolated.
# Fails (non-zero) on the first red suite. Expects: pytest, panda3d,
# cargo all present (see Dockerfile).
set -eu

cd /app

echo "=== 1/6 python suite (core, adapters incl. REAL Panda3D, bridge, forge) ==="
python -c "from direct.task.Task import TaskManager; print('panda3d OK')"
python -m pytest tests/ -q -p no:cacheprovider

echo "=== 2/6 rust client (pure unit tests) ==="
(cd clients/rust && cargo test --offline -q)

echo "=== 3/6 rust client (live, against real BridgeServer) ==="
python examples/bridge_server.py --port 8471 >/tmp/bridge.log 2>&1 &
BRIDGE_PID=$!
trap 'kill $BRIDGE_PID 2>/dev/null' EXIT
python - <<'EOF'
import time, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(100):
    try:
        opener.open("http://127.0.0.1:8471/v1/health", timeout=2).read()
        break
    except Exception:
        time.sleep(0.2)
else:
    raise SystemExit("bridge never came up")
EOF
(cd clients/rust && cargo test --offline -q -- --ignored)
kill $BRIDGE_PID 2>/dev/null || true
trap - EXIT

echo "=== 4/6 bevy client (headless plugin tests, no server) ==="
(cd clients/bevy && cargo test --offline -q)

echo "=== 5/6 restaurant game (scripted playthrough over HTTP) ==="
NPC_CORTEX_FAKE_LLM=1 python games/restaurant/smoke_play.py

echo "=== 6/6 native-client file check (unity/unreal/godot ship tests) ==="
ls clients/unity/Tests/NpcCortexClientTests.cs \
   clients/unreal/NpcCortexClient.spec.cpp \
   clients/godot/tests/test_npc_cortex_client.gd >/dev/null
echo "(compiled in-engine; protocol covered by tests/clients/)"

echo "SMOKE-GREEN: all suites passed."
