"""Bridge server tests (HTTP wire behaviour, raw urllib)."""

import json
import urllib.request

import pytest

from conftest import Scripted, answer, make_world
from npc_cortex.server import BridgeServer


@pytest.fixture()
def server():
    _, rt = make_world(Scripted(answer(speech="hi", actions=[("wave", {"target": "p1"})])))
    rt.registry.register("wave", {"target": str}, 0.0,
                         lambda s, n, p: None)
    srv = BridgeServer(rt)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()
        rt.close()


# Localhost traffic must bypass proxies from the environment.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def get(base, path):
    with _OPENER.open(base + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_health(server):
    status, body = get(server.base_url, "/v1/health")
    assert status == 200 and body["ok"] is True
    assert body["engine"] == "npc-cortex"


def test_submit_pump_delivers(server):
    post(server.base_url, "/v1/submit",
         {"kind": "tick", "npc_id": "n1", "speaker_id": None, "text": None})
    resolved = 0
    for _ in range(200):
        _, body = post(server.base_url, "/v1/pump", {})
        resolved += body["resolved"]
        if resolved:
            break
    assert resolved == 1
    _, body = get(server.base_url, "/v1/delivered?since=0")
    assert body["delivered"] == [["p1", "hi"]]
    assert body["next_since"] == 1


def test_registered_remote_action_lands_in_feed():
    _, rt = make_world(Scripted(answer(actions=[("jump", {"height": 2})])))
    srv = BridgeServer(rt)
    srv.start()
    try:
        post(srv.base_url, "/v1/register_action",
             {"name": "jump", "parameters": {"height": "int"},
              "min_implication": 0.0, "broadcast": False})
        post(srv.base_url, "/v1/submit", {"kind": "tick", "npc_id": "n1"})
        for _ in range(200):
            _, body = post(srv.base_url, "/v1/pump", {})
            if body["resolved"]:
                break
        _, body = get(srv.base_url, "/v1/actions?since=0")
        assert len(body["actions"]) == 1
        entry = body["actions"][0]
        assert (entry["name"], entry["parameters"]) == ("jump", {"height": 2})
        assert entry["actor_id"] == "n1" and entry["broadcast"] is False
    finally:
        srv.stop()
        rt.close()


def test_remote_type_system_rejects_mismatch():
    _, rt = make_world(Scripted(answer(actions=[("jump", {"height": "high"})])))
    srv = BridgeServer(rt)
    srv.start()
    try:
        post(srv.base_url, "/v1/register_action",
             {"name": "jump", "parameters": {"height": "int"}})
        post(srv.base_url, "/v1/submit", {"kind": "tick", "npc_id": "n1"})
        for _ in range(200):
            _, body = post(srv.base_url, "/v1/pump", {})
            if body["resolved"]:
                break
        _, body = get(srv.base_url, "/v1/actions?since=0")
        assert body["actions"] == []
        _, audit = get(srv.base_url, "/v1/audit?since=0")
        assert audit["records"][-1]["kind"] == "action_rejected"
    finally:
        srv.stop()
        rt.close()


def test_sync_upserts_characters(server):
    _, body = post(server.base_url, "/v1/sync", {
        "players": [{"id": "p2", "position": [5, 5, 5], "role": "mage"}],
        "npcs": [{"id": "n1", "position": [9, 9]}],
        "world_state": {"q": 1},
    })
    assert body == {"ok": True, "players": 2, "npcs": 1}
    assert server.runtime.scenario.players[1].position == (5.0, 5.0, 5.0)
    assert server.runtime.scenario.npcs[0].position == (9.0, 9.0)
    assert server.runtime.scenario.world_state == {"q": 1}


def test_surroundings_lists_nearby_places_without_private_facts(server):
    from npc_cortex.places import Place
    server.runtime.scenario.places = [
        Place(id="barn", coords=(2.0, 1.0), kind="building",
              description="Stone barn.", owner="cask", public=False,
              interior="Counting room."),
    ]
    _, body = get(server.base_url, "/v1/surroundings?npc_id=n1&radius=50")
    assert [p["id"] for p in body["places"]] == ["barn"]
    assert set(body["places"][0]) == {"id", "kind", "distance",
                                      "description", "public"}
    _, body = get(server.base_url, "/v1/surroundings?npc_id=n1&radius=0.5")
    assert body["places"] == []


def test_knowledge_returns_history_and_acquaintances(server):
    post(server.base_url, "/v1/submit",
         {"kind": "tick", "npc_id": "n1", "speaker_id": None, "text": None})
    for _ in range(200):
        _, body = post(server.base_url, "/v1/pump", {})
        if body["resolved"]:
            break
    _, body = get(server.base_url, "/v1/knowledge?npc_id=p1")
    assert len(body["history"]) == 1  # p1 saw n1 wave ...
    assert body["acquaintances"] == {}  # ... but only NPCs befriend
    _, body = get(server.base_url, "/v1/knowledge?npc_id=n1")
    assert body == {"history": [], "acquaintances": {}}  # no self-records
    _, body = get(server.base_url, "/v1/knowledge?npc_id=p1&actor_id=n1&limit=5")
    assert len(body["history"]) == 1
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(server.base_url, "/v1/knowledge?npc_id=p1&limit=nope")
    assert exc.value.code == 400


def test_unknown_routes_and_bad_bodies_are_400_or_404(server):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(server.base_url, "/v1/nope")
    assert exc.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(server.base_url, "/v1/submit", {"kind": "tick"})
    assert exc.value.code == 400
