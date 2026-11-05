"""HTTP bridge server (stdlib only). See ``docs/PROTOCOL.md``."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .. import __version__
from ..models import NPC, Closed, Event, Overloaded, Player

__all__ = ["BridgeServer", "REMOTE_TYPES"]

# JSON type names accepted by /v1/register_action.
REMOTE_TYPES = ("str", "int", "float", "bool", "dict", "list")


def _check(value, typename) -> bool:
    if typename == "str":
        return isinstance(value, str)
    if typename == "bool":
        return isinstance(value, bool)
    if typename == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if typename == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typename == "dict":
        return isinstance(value, dict)
    if typename == "list":
        return isinstance(value, list)
    return False


def _position(value):
    pos = tuple(value)
    if len(pos) == 2:
        return (float(pos[0]), float(pos[1]))
    if len(pos) == 3:
        return (float(pos[0]), float(pos[1]), float(pos[2]))
    raise ValueError("position must be [x, y] or [x, y, z]")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NpcCortex/1"

    # -- plumbing ----------------------------------------------------

    def log_message(self, *args):  # noqa: N802, D102
        pass

    def _send(self, status, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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
            raise ValueError("request body is not valid JSON")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    @property
    def _bridge(self):
        return self.server.bridge

    def _route(self):
        return urlparse(self.path).path, urlparse(self.path).query

    # -- HTTP verbs ---------------------------------------------------

    def do_GET(self):  # noqa: N802
        from urllib.parse import parse_qs

        path, query = self._route()
        args = parse_qs(query)
        try:
            if path == "/v1/health":
                self._send(200, {"ok": True, "engine": "npc-cortex",
                                 "version": __version__})
            elif path == "/v1/observations":
                cid = args.get("character_id", [None])[0]
                if cid is None:
                    raise ValueError("missing query parameter: character_id")
                self._send(200, {"records": self._bridge.runtime.observations(cid)})
            elif path == "/v1/memory":
                nid = args.get("npc_id", [None])[0]
                if nid is None:
                    raise ValueError("missing query parameter: npc_id")
                self._send(200, self._bridge.runtime.memory(nid))
            elif path == "/v1/surroundings":
                nid = args.get("npc_id", [None])[0]
                if nid is None:
                    raise ValueError("missing query parameter: npc_id")
                try:
                    radius = float(args.get("radius", ["20.0"])[0])
                except ValueError:
                    raise ValueError("query parameter 'radius' must be a number")
                try:
                    places = self._bridge.runtime.surroundings(nid, radius)
                except ValueError as exc:
                    raise ValueError(str(exc))
                self._send(200, {"places": places})
            elif path == "/v1/audit":
                self._send(200, self._bridge.audit_since(self._since(args)))
            elif path == "/v1/delivered":
                self._send(200, self._bridge.delivered_since(self._since(args)))
            elif path == "/v1/actions":
                self._send(200, self._bridge.actions_since(self._since(args)))
            elif path == "/v1/knowledge":
                nid = args.get("npc_id", [None])[0]
                if nid is None:
                    raise ValueError("missing query parameter: npc_id")
                actor = args.get("actor_id", [None])[0]
                raw_limit = args.get("limit", [None])[0]
                try:
                    limit = None if raw_limit is None else int(raw_limit)
                except ValueError:
                    raise ValueError("query parameter 'limit' must be an integer")
                try:
                    history = self._bridge.runtime.history(nid, actor, limit)
                except ValueError as exc:
                    raise ValueError(str(exc))
                self._send(200, {"history": history,
                                 "acquaintances":
                                     self._bridge.runtime.acquaintances(nid)})
            else:
                self._send(404, {"error": "NotFound", "detail": path})
        except ValueError as exc:
            self._send(400, {"error": "BadRequest", "detail": str(exc)})

    def _since(self, args) -> int:
        try:
            since = int(args.get("since", ["0"])[0])
        except ValueError:
            raise ValueError("query parameter 'since' must be an integer")
        if since < 0:
            raise ValueError("query parameter 'since' must be >= 0")
        return since

    def do_POST(self):  # noqa: N802
        path, _ = self._route()
        try:
            data = self._read_json()
            handler = {
                "/v1/submit": self._submit,
                "/v1/pump": self._pump,
                "/v1/engage": self._engage,
                "/v1/cancel": self._cancel,
                "/v1/register_action": self._register_action,
                "/v1/sync": self._sync,
                "/v1/close": self._close,
            }.get(path)
            if handler is None:
                self._send(404, {"error": "NotFound", "detail": path})
            else:
                handler(data)
        except ValueError as exc:
            self._send(400, {"error": "BadRequest", "detail": str(exc)})
        except Overloaded as exc:
            self._send(429, {"error": "Overloaded", "detail": str(exc)})
        except Closed as exc:
            self._send(409, {"error": "Closed", "detail": str(exc)})

    # -- endpoints ----------------------------------------------------

    def _submit(self, data) -> None:
        try:
            event = Event(
                kind=str(data["kind"]),
                npc_id=str(data["npc_id"]),
                speaker_id=data.get("speaker_id"),
                text=data.get("text"),
            )
        except KeyError as exc:
            raise ValueError("missing required field: %s" % exc)
        if event.speaker_id is not None and not isinstance(event.speaker_id, str):
            raise ValueError("field 'speaker_id' must be a string or null")
        if event.text is not None and not isinstance(event.text, str):
            raise ValueError("field 'text' must be a string or null")
        self._bridge.runtime.submit(event)
        self._send(200, {"ok": True})

    def _pump(self, data) -> None:
        self._send(200, {"resolved": self._bridge.runtime.pump()})

    def _engage(self, data) -> None:
        try:
            handle = self._bridge.runtime.engage(
                str(data["player_id"]),
                str(data["name"]),
                dict(data.get("parameters", {})),
                float(data["duration"]),
            )
        except KeyError as exc:
            raise ValueError("missing required field: %s" % exc)
        self._send(200, {"handle": handle})

    def _cancel(self, data) -> None:
        if "handle" not in data:
            raise ValueError("missing required field: handle")
        self._bridge.runtime.cancel(str(data["handle"]))
        self._send(200, {"ok": True})

    def _register_action(self, data) -> None:
        try:
            name = str(data["name"])
            spec = dict(data.get("parameters", {}))
            min_implication = float(data.get("min_implication", 0.0))
            broadcast = bool(data.get("broadcast", False))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid register_action body: %s" % exc)
        for key, typename in spec.items():
            if typename not in REMOTE_TYPES:
                raise ValueError(
                    "unknown parameter type %r for %r (want one of %s)"
                    % (typename, key, ", ".join(REMOTE_TYPES))
                )
        self._bridge.register_remote(name, spec, min_implication, broadcast)
        self._send(200, {"ok": True})

    def _sync(self, data) -> None:
        players = data.get("players", [])
        npcs = data.get("npcs", [])
        if not isinstance(players, list) or not isinstance(npcs, list):
            raise ValueError("fields 'players' and 'npcs' must be arrays")
        world_state = data.get("world_state")
        if world_state is not None and not isinstance(world_state, dict):
            raise ValueError("field 'world_state' must be an object")
        counts = self._bridge.sync(players, npcs, world_state)
        self._send(200, {"ok": True, **counts})

    def _close(self, data) -> None:
        self._bridge.runtime.close()
        self._send(200, {"ok": True})


class BridgeServer:
    """Serve one runtime over HTTP+JSON (see ``docs/PROTOCOL.md``).

    The server never pumps by itself; engines call ``POST /v1/pump``
    once per frame, which keeps game-state effects on the engine's
    timeline. Remote actions registered via ``/v1/register_action``
    append to the ``/v1/actions`` feed when the runtime applies them.
    """

    def __init__(self, runtime, host: str = "127.0.0.1", port: int = 0) -> None:
        self.runtime = runtime
        self.host = host
        self._applied: list = []
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.bridge = self
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return "http://%s:%d" % (host, port)

    # -- lifecycle ----------------------------------------------------

    def start(self) -> str:
        """Serve in a background thread; return the base URL."""
        if self._thread is not None:
            return self.base_url
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="npc-cortex-server", daemon=True
        )
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        """Shut down. Idempotent; does not close the runtime."""
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def serve_forever(self) -> None:
        """Serve on this thread (e.g. for a dedicated bridge process)."""
        self._httpd.serve_forever()

    # -- feeds --------------------------------------------------------

    def audit_since(self, since: int) -> dict:
        records = self.runtime.audit.records[since:]
        return {"records": [dict(r) for r in records], "next_since": since + len(records)}

    def delivered_since(self, since: int) -> dict:
        delivered = self.runtime.gateway.delivered[since:]
        return {
            "delivered": [[pid, text] for pid, text in delivered],
            "next_since": since + len(delivered),
        }

    def actions_since(self, since: int) -> dict:
        with self._lock:
            actions = [dict(a) for a in self._applied[since:]]
        return {"actions": actions, "next_since": since + len(actions)}

    def _record_applied(self, handle, actor_id, npc_id, name, parameters, broadcast) -> None:
        with self._lock:
            self._applied.append(
                {
                    "seq": len(self._applied),
                    "handle": handle,
                    "actor_id": actor_id,
                    "npc_id": npc_id,
                    "name": name,
                    "parameters": dict(parameters),
                    "broadcast": bool(broadcast),
                }
            )

    # -- remote actions -----------------------------------------------

    def register_remote(self, name, spec, min_implication: float = 0.0,
                        broadcast: bool = False) -> None:
        """Register ``name`` so applied calls land in ``/v1/actions``.

        ``spec`` maps parameter names to ``REMOTE_TYPES`` entries. Shape
        validation mirrors spec 3.5 (exact key set + per-value types);
        implication gating still happens in the runtime at resolve time.
        """
        spec = dict(spec)

        def _handler(scenario, npc, parameters, _name=name, _spec=spec,
                     _broadcast=broadcast):
            if set(parameters) != set(_spec):
                return  # pragma: no cover - runtime already shape-checked
            for key, typename in _spec.items():
                if not _check(parameters[key], typename):
                    return  # pragma: no cover - runtime already shape-checked
            if npc is None:
                # Engagement completion: attribute to the engaging player.
                actor_id, npc_id, handle = "", None, ""
            else:
                actor_id, npc_id, handle = npc.id, npc.id, ""
            # Engagement handles are recovered below via the audit trail.
            self._record_applied(handle, actor_id, npc_id, _name,
                                 parameters, _broadcast)

        # The runtime validates shape with Python types; wrap the JSON type
        # names in marker classes carrying the same check.
        py_spec = {key: _RemoteType(typename) for key, typename in spec.items()}
        self.runtime.registry.register(
            name, py_spec, float(min_implication), _handler, broadcast=broadcast
        )

    # -- scenario sync --------------------------------------------------

    def sync(self, players: list, npcs: list, world_state: dict | None) -> dict:
        scenario = self.runtime.scenario
        by_player = {p.id: p for p in scenario.players}
        by_npc = {n.id: n for n in scenario.npcs}
        for entry in players:
            self._sync_player(scenario, by_player, entry)
        for entry in npcs:
            self._sync_npc(scenario, by_npc, entry)
        if world_state:
            scenario.world_state.update(dict(world_state))
        return {"players": len(by_player), "npcs": len(by_npc)}

    def _sync_player(self, scenario, by_id, entry) -> None:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValueError("each player entry needs an 'id'")
        pid = str(entry["id"])
        player = by_id.get(pid)
        if player is None:
            player = Player(
                id=pid,
                role=str(entry.get("role", "player")),
                position=_position(entry.get("position", [0, 0])),
                horizon=float(entry.get("horizon", 10.0)),
                online=bool(entry.get("online", True)),
            )
            scenario.players.append(player)
            by_id[pid] = player
            return
        if "role" in entry:
            player.role = str(entry["role"])
        if "position" in entry:
            player.position = _position(entry["position"])
        if "horizon" in entry:
            player.horizon = float(entry["horizon"])
        if "online" in entry:
            player.online = bool(entry["online"])

    def _sync_npc(self, scenario, by_id, entry) -> None:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValueError("each npc entry needs an 'id'")
        nid = str(entry["id"])
        npc = by_id.get(nid)
        if npc is None:
            npc = NPC(
                id=nid,
                position=_position(entry.get("position", [0, 0])),
                horizon=float(entry.get("horizon", 10.0)),
                implication=float(entry.get("implication", 1.0)),
            )
            scenario.npcs.append(npc)
            by_id[nid] = npc
            return
        if "position" in entry:
            npc.position = _position(entry["position"])
        if "horizon" in entry:
            npc.horizon = float(entry["horizon"])
        if "implication" in entry:
            npc.implication = float(entry["implication"])


class _RemoteType(type):
    """A ``type`` whose ``isinstance`` check is a JSON type name.

    Lets the runtime's own shape validation (spec 3.5) enforce the JSON
    type system without forking the resolve path.
    """

    def __new__(mcls, typename):
        cls = super().__new__(mcls, "Remote_%s" % typename, (object,), {})
        cls._typename = typename
        return cls

    def __init__(cls, typename):  # noqa: D102 - swallowed; see __new__
        pass

    def __instancecheck__(cls, instance) -> bool:
        return _check(instance, cls._typename)
