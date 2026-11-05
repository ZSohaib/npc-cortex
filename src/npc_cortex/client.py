"""Reference network client (stdlib only).

:class:`RemoteBridge` speaks ``docs/PROTOCOL.md`` to a
:class:`~npc_cortex.server.BridgeServer`. Unity, Unreal, and Godot
native clients (``clients/``) mirror this API method for method, so
this module doubles as the executable specification the conformance
tests run against.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .models import Closed, Overloaded

__all__ = ["RemoteBridge", "BridgeError"]


class BridgeError(Exception):
    """The server answered 4xx/5xx with an unmapped error name."""


class RemoteBridge:
    """Thin JSON client for one bridge server. Mirrors ``Runtime``."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        # The bridge is local game traffic: never route it through a proxy
        # from the environment (proxy env vars would otherwise capture even
        # localhost URLs and break or stall the frame loop).
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- transport ----------------------------------------------------

    def _call(self, method, path, body=None, query=None):
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            name = payload.get("error", "")
            detail = payload.get("detail", "")
            if name == "Overloaded":
                raise Overloaded(detail)
            if name == "Closed":
                raise Closed(detail)
            raise BridgeError("%s: %s" % (name or exc.code, detail))

    # -- runtime mirror -------------------------------------------------

    def health(self) -> dict:
        """``GET /v1/health``."""
        return self._call("GET", "/v1/health")

    def submit(self, kind: str, npc_id: str, speaker_id=None, text=None) -> None:
        """``POST /v1/submit``. Raises ``Overloaded``/``Closed`` like
        ``Runtime.submit()``."""
        self._call("POST", "/v1/submit", {
            "kind": kind, "npc_id": npc_id,
            "speaker_id": speaker_id, "text": text,
        })

    def pump(self) -> int:
        """``POST /v1/pump``. Returns the resolved count."""
        return int(self._call("POST", "/v1/pump", {})["resolved"])

    def engage(self, player_id: str, name: str, parameters: dict, duration: float) -> str:
        """``POST /v1/engage``. Returns the handle."""
        return str(self._call("POST", "/v1/engage", {
            "player_id": player_id, "name": name,
            "parameters": dict(parameters), "duration": float(duration),
        })["handle"])

    def cancel(self, handle: str) -> None:
        """``POST /v1/cancel``."""
        self._call("POST", "/v1/cancel", {"handle": handle})

    def observations(self, character_id: str) -> list:
        """``GET /v1/observations``."""
        return list(self._call("GET", "/v1/observations",
                               query={"character_id": character_id})["records"])

    def memory(self, npc_id: str) -> dict:
        """``GET /v1/memory``."""
        return dict(self._call("GET", "/v1/memory", query={"npc_id": npc_id}))

    def surroundings(self, npc_id: str, radius: float = 20.0) -> list:
        """``GET /v1/surroundings``: nearby places, nearest first."""
        return list(self._call("GET", "/v1/surroundings", query={
            "npc_id": npc_id, "radius": float(radius)})["places"])

    def knowledge(self, npc_id: str, actor_id=None, limit=None) -> dict:
        """``GET /v1/knowledge``: ``{"history", "acquaintances"}`` -- what
        ``npc_id`` developed about others (optionally one actor)."""
        query = {"npc_id": npc_id}
        if actor_id is not None:
            query["actor_id"] = actor_id
        if limit is not None:
            query["limit"] = int(limit)
        out = self._call("GET", "/v1/knowledge", query=query)
        return {"history": list(out["history"]),
                "acquaintances": dict(out["acquaintances"])}

    def audit(self, since: int = 0) -> dict:
        """``GET /v1/audit``. Returns ``{"records", "next_since"}``."""
        out = self._call("GET", "/v1/audit", query={"since": int(since)})
        return {"records": list(out["records"]), "next_since": int(out["next_since"])}

    def delivered(self, since: int = 0) -> dict:
        """``GET /v1/delivered``. Returns ``{"delivered", "next_since"}``."""
        out = self._call("GET", "/v1/delivered", query={"since": int(since)})
        return {"delivered": [tuple(p) for p in out["delivered"]],
                "next_since": int(out["next_since"])}

    def actions(self, since: int = 0) -> dict:
        """``GET /v1/actions``. Returns ``{"actions", "next_since"}``."""
        out = self._call("GET", "/v1/actions", query={"since": int(since)})
        return {"actions": list(out["actions"]),
                "next_since": int(out["next_since"])}

    def register_action(self, name: str, parameters: dict,
                        min_implication: float = 0.0, broadcast: bool = False) -> None:
        """``POST /v1/register_action``. ``parameters`` maps names to JSON
        type names (``str``, ``int``, ``float``, ``bool``, ``dict``,
        ``list``)."""
        self._call("POST", "/v1/register_action", {
            "name": name, "parameters": dict(parameters),
            "min_implication": float(min_implication), "broadcast": bool(broadcast),
        })

    def sync(self, players=(), npcs=(), world_state=None) -> dict:
        """``POST /v1/sync``. Upserts characters from engine state."""
        body: dict = {"players": list(players), "npcs": list(npcs)}
        if world_state is not None:
            body["world_state"] = dict(world_state)
        return dict(self._call("POST", "/v1/sync", body))

    def close(self) -> None:
        """``POST /v1/close``."""
        self._call("POST", "/v1/close", {})
