#!/usr/bin/env python3
"""Scripted playthrough of Maison Cinq over HTTP (local + docker smoke).

Starts the game server in-process, plays: talk, order, pay, role swap,
action, language swap, passive gating, and asserts the economy moved.
Prints PLAY-GREEN on success; raises otherwise.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from server import Game, _Handler  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main(port=8909):
    import os
    # Deterministic stand-in unless the operator configured a real key.
    os.environ.setdefault("NPC_CORTEX_FAKE_LLM", "1")
    game = Game(out_dir=HERE / "out-smoke")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.daemon_threads = True
    httpd.game = game
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % port

    def pump(seconds):
        # Steps on the main thread: real Panda3D forbids stepping elsewhere.
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            game.step()

    try:
        get = lambda path: json.loads(
            _OPENER.open(base + path, timeout=5).read())

        def post(path, body):
            req = urllib.request.Request(
                base + path, data=json.dumps(body).encode(), method="POST",
                headers={"Content-Type": "application/json"})
            with _OPENER.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())

        with _OPENER.open(base + "/", timeout=5) as resp:
            assert b"Maison Cinq" in resp.read(), "no UI served"
        state = get("/api/state")
        assert len(state["entities"]) >= 15, "thin cast: %d" % len(state["entities"])
        assert len(state["tables"]) == 6

        post("/api/talk", {"to": "auguste", "text": "bonsoir chef"})
        post("/api/act", {"action": "order_dish",
                          "params": {"dish": "Bouillabaisse"}})
        _, paid = post("/api/act", {"action": "pay_bill", "params": {}})
        assert paid["result"]["paid"] == 32, paid
        post("/api/role", {"role": "waiter"})
        post("/api/lang", {"lang": "arabic"})
        post("/api/mode", {"mode": "passive"})
        try:
            post("/api/talk", {"to": "nina", "text": "hi"})
            raise AssertionError("passive talk should be forbidden")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, exc.code
        post("/api/mode", {"mode": "active"})
        # let service run; revenue must move (tab + served tables)
        end = time.monotonic() + 40
        while time.monotonic() < end:
            pump(1.0)
            state = get("/api/state")
            if state["stats"]["revenue"] >= 32 and state["stats"]["served"] >= 1:
                break
        assert state["stats"]["revenue"] >= 32, state["stats"]
        assert state["stats"]["served"] >= 1, state["stats"]
        print("PLAY-GREEN: revenue=%(revenue)d served=%(served)d rating=%(rating)s"
              % state["stats"])
    finally:
        game.stop()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8909)
