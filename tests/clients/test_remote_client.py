"""Reference client tests (RemoteBridge end to end vs a live server)."""

import time

import pytest

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.client import RemoteBridge
from npc_cortex.server import BridgeServer


@pytest.fixture()
def bridge():
    _, rt = make_world(Scripted(answer(speech="hello",
                                       actions=[("wave", {"target": "p1"})])))
    srv = BridgeServer(rt)
    base = srv.start()
    try:
        yield RemoteBridge(base), rt
    finally:
        srv.stop()
        rt.close()


def pump_until(client, want=1, timeout=5.0):
    resolved, end = 0, time.monotonic() + timeout
    while resolved < want and time.monotonic() < end:
        resolved += client.pump()
    assert resolved == want


def test_frame_flow_submit_pump_poll(bridge):
    client, rt = bridge
    assert client.health()["ok"] is True
    client.register_action("wave", {"target": "str"})
    client.sync(players=[{"id": "p1", "position": [0, 0, 0]}],
                npcs=[{"id": "n1", "position": [1, 0, 0]}])
    client.submit("direct_message", "n1", speaker_id="p1", text="hey")
    pump_until(client)
    fed = client.actions()
    assert len(fed["actions"]) == 1
    assert fed["actions"][0]["name"] == "wave"
    assert client.delivered()["delivered"] == [("p1", "hello")]
    assert client.observations("p1")[0]["phase"] == "completed"
    assert set(client.memory("n1")) == {"players", "npcs"}
    assert client.audit()["records"][0]["kind"] == "action_accepted"


def test_engage_cancel_round_trip(bridge):
    client, rt = bridge
    client.register_action("escort", {})
    handle = client.engage("p1", "escort", {}, 30.0)
    assert handle.startswith("engagement-")
    client.pump()
    client.cancel(handle)
    client.pump()
    # n1 perceives the engaging player p1 (nobody perceives its own actions).
    obs = [r for r in client.observations("n1") if r["handle"] == handle]
    assert [r["phase"] for r in obs] == ["started", "cancelled"]


def test_cancel_unknown_handle_is_inert(bridge):
    client, _ = bridge
    client.cancel("engagement-424242")


def test_client_knowledge(bridge):
    client, _ = bridge
    client.register_action("wave", {"target": "str"})
    client.submit("tick", "n1")
    pump_until(client)
    out = client.knowledge("p1")
    assert len(out["history"]) == 1
    assert out["acquaintances"] == {}
    assert client.knowledge("p1", actor_id="n1", limit=1)["history"] == out["history"]
    assert client.knowledge("ghost") == {"history": [], "acquaintances": {}}


def test_client_surroundings(bridge):
    from npc_cortex.places import Place
    client, rt = bridge
    rt.scenario.places = [Place(id="well", coords=(1.0, 1.0),
                                kind="landmark", description="Old well.",
                                public=True)]
    out = client.surroundings("n1", radius=50.0)
    assert [p["id"] for p in out] == ["well"]
    assert client.surroundings("ghost") == []


def test_overloaded_and_closed_map_to_exceptions():
    _, rt = make_world(Scripted(answer(), delay=30.0), capacity=1,
                       call_timeout=60.0)
    srv = BridgeServer(rt)
    client = RemoteBridge(srv.start())
    try:
        client.submit("tick", "n1")
        with pytest.raises(m.Overloaded):
            client.submit("tick", "n1")
        client.close()
        with pytest.raises(m.Closed):
            client.submit("tick", "n1")
        with pytest.raises(m.Closed):
            client.pump()
        client.cancel("engagement-1")  # still inert
    finally:
        srv.stop()
        rt.close()
