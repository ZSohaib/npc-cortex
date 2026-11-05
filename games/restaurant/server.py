"""Maison Cinq web server: Panda3D sim + npc-cortex, playable in a browser.

Needs a live LLM (``NPC_CORTEX_API_KEY`` + ``NPC_CORTEX_ENDPOINT`` +
``NPC_CORTEX_MODEL``); without them the server refuses to boot.
``NPC_CORTEX_FAKE_LLM=1`` selects the test-only stand-in.

Run from the repo root::

    python3 games/restaurant/server.py --port 8901

then open http://127.0.0.1:8901 in a browser. One background thread
steps the Panda3D task manager (sim tick + runtime pump); HTTP handlers
only read snapshots and forward talk/act/mode/role/lang calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from provider import LLMNotConfigured, build_provider, key_status  # noqa: E402
from sim import Sim, make_task_manager  # noqa: E402

STATIC = {"index.html", "style.css", "game.js"}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MaisonCinq/1"

    def log_message(self, *args):  # noqa: N802, D102
        pass

    @property
    def _game(self):
        return self.server.game

    def _send(self, status, payload, content_type="application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            raise ValueError("body is not valid JSON")
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/index.html"):
                self._send(200, (HERE / "static" / "index.html").read_bytes(),
                           "text/html; charset=utf-8")
            elif parsed.path.startswith("/static/"):
                rel = parsed.path[len("/static/"):]
                if "/" in rel:
                    parts = rel.split("/")
                    if len(parts) != 2 or parts[0] != "assets":
                        self._send(404, {"error": "NotFound"})
                        return
                    name = parts[1]
                    if not name or ".." in name or "/" in name:
                        self._send(404, {"error": "NotFound"})
                        return
                    ctype = ("image/png" if name.endswith(".png")
                             else "image/jpeg" if name.endswith((".jpg", ".jpeg"))
                             else "application/json" if name.endswith(".json")
                             else "application/octet-stream")
                    target = HERE / "static" / "assets" / name
                    if not target.is_file():
                        self._send(404, {"error": "NotFound"})
                        return
                    self._send(200, target.read_bytes(), ctype)
                    return
                if rel not in STATIC:
                    self._send(404, {"error": "NotFound"})
                    return
                ctype = ("text/css" if rel.endswith(".css")
                         else "text/javascript" if rel.endswith(".js")
                         else "text/html; charset=utf-8")
                self._send(200, (HERE / "static" / rel).read_bytes(), ctype)
            elif parsed.path == "/api/state":
                cursor = 0
                query = dict(part.split("=", 1) for part in
                             parsed.query.split("&") if "=" in part)
                if "cursor" in query:
                    cursor = int(query["cursor"])
                with self._game.lock:
                    state = self._game.sim.state(delivered_since=cursor)
                state["key"] = key_status()
                self._send(200, state)
            else:
                self._send(404, {"error": "NotFound"})
        except ValueError as exc:
            self._send(400, {"error": "BadRequest", "detail": str(exc)})

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
            if parsed.path == "/api/talk":
                with self._game.lock:
                    self._game.sim.talk(str(data["to"]), str(data.get("text", "")))
                self._send(200, {"ok": True})
            elif parsed.path == "/api/act":
                with self._game.lock:
                    out = self._game.sim.player_act(
                        str(data["action"]), dict(data.get("params", {})))
                self._send(200, {"ok": True, "result": out})
            elif parsed.path == "/api/mode":
                mode = str(data.get("mode", ""))
                if mode not in ("active", "passive"):
                    raise ValueError("mode must be active|passive")
                with self._game.lock:
                    self._game.sim.mode = mode
                self._send(200, {"ok": True, "mode": mode})
            elif parsed.path == "/api/role":
                with self._game.lock:
                    role = self._game.sim.set_role(str(data.get("role", "")))
                self._send(200, {"ok": True, "role": role})
            elif parsed.path == "/api/lang":
                lang = str(data.get("lang", ""))
                if lang not in ("english", "french", "spanish", "arabic"):
                    raise ValueError("unsupported language")
                with self._game.lock:
                    self._game.sim.lang = lang
                self._send(200, {"ok": True, "lang": lang})
            elif parsed.path == "/api/move":
                with self._game.lock:
                    self._game.sim.move_player(data.get("x"), data.get("y"))
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "NotFound"})
        except PermissionError as exc:
            self._send(403, {"error": "Forbidden", "detail": str(exc)})
        except KeyError as exc:
            self._send(404, {"error": "NotFound", "detail": "unknown person"})
        except ValueError as exc:
            self._send(400, {"error": "BadRequest", "detail": str(exc)})


class Game:
    """Owns the sim and its task manager.

    Stepping happens wherever the caller steps: real Panda3D installs a
    SIGINT handler inside ``task_mgr.step()``, so production stepping
    runs on the main thread (see ``serve()``); tests step manually.
    """

    def __init__(self, out_dir=None) -> None:
        self.lock = threading.Lock()
        self.task_mgr = make_task_manager()
        self.sim = Sim(build_provider(), out_dir=out_dir)
        self.sim.attach(self.task_mgr)

    def start(self):
        """Kept for fluent construction; stepping is caller-driven."""
        return self

    def step(self):
        with self.lock:
            self.task_mgr.step()

    def stop(self):
        with self.lock:
            self.sim.close()


def serve(port: int = 8901, out_dir=None):
    try:
        game = Game(out_dir=out_dir)
    except LLMNotConfigured as exc:
        print("Maison Cinq needs a live LLM: %s" % exc, flush=True)
        raise SystemExit(2)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.daemon_threads = True
    httpd.game = game
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print("Maison Cinq at http://127.0.0.1:%d  (Ctrl-C to stop)" % port,
          flush=True)
    try:
        while True:
            start = time.monotonic()
            game.step()
            time.sleep(max(0.0, 0.1 - (time.monotonic() - start)))
    except KeyboardInterrupt:
        pass
    finally:
        game.stop()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Maison Cinq restaurant game")
    parser.add_argument("--port", type=int, default=8901)
    parser.add_argument("--out", default=None,
                        help="forge output dir (default games/restaurant/out)")
    args = parser.parse_args(argv)
    serve(args.port, args.out)


if __name__ == "__main__":
    main()
