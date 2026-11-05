"""Acquaintance tests: NPCs develop knowledge about each other."""

import pytest

import npc_cortex as m
from conftest import Scripted, answer, drain, make_world


def _duo(provider, action="wave"):
    """n1 acts, n2 watches. Returns (scenario, runtime)."""
    players = [m.Player(id="p1", role="s", position=(0.0, 0.0),
                        horizon=50.0, online=True)]
    npcs = [m.NPC(id="n1", position=(1.0, 0.0), horizon=50.0, implication=0.5),
            m.NPC(id="n2", position=(2.0, 0.0), horizon=50.0, implication=0.5)]
    scenario, rt = make_world(provider, players=players, npcs=npcs)
    rt.registry.register(action, {}, 0.0, lambda s, n, p: None)
    return scenario, rt


def _act(rt, npc_id, times, text="go"):
    for i in range(times):
        rt.submit(m.Event(kind="tick", npc_id=npc_id, text="%s%d" % (text, i)))
    drain(rt, times)


def test_repeated_deeds_build_warm_acquaintance():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 3)
    friends = rt.acquaintances("n2")
    assert friends["n1"]["interactions"] == 3
    assert friends["n1"]["completed"] == 3
    assert friends["n1"]["cancelled"] == 0
    assert friends["n1"]["actions"] == {"wave": 3}
    assert friends["n1"]["disposition"] == "warm"
    assert friends["n1"]["first_seen"] <= friends["n1"]["last_seen"]


def test_cancelled_deeds_build_wary_acquaintance():
    _, rt = _duo(Scripted(answer()))
    rt.registry.register("escort", {}, 0.0, lambda s, n, p: None)
    for _ in range(2):  # two engaged-then-cancelled player deeds, seen by n2
        handle = rt.engage("p1", "escort", {}, 30.0)
        rt.pump()
        rt.cancel(handle)
        rt.pump()
    friends = rt.acquaintances("n2")
    assert friends["p1"]["cancelled"] == 2
    assert friends["p1"]["disposition"] == "wary"


def test_single_meeting_stays_neutral():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 1)
    assert rt.acquaintances("n2")["n1"]["disposition"] == "neutral"


def test_history_filters_by_actor_and_window():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 3)
    full = rt.history("n2")
    assert len(full) == 3 and all(r["actor_id"] == "n1" for r in full)
    assert rt.history("n2", actor_id="n1") == full
    assert rt.history("n2", actor_id="p1") == []
    assert rt.history("n2", limit=2) == full[-2:]
    assert rt.history("n2", limit=0) == []
    with pytest.raises(ValueError):
        rt.history("n2", limit=-1)


def test_players_have_histories_but_no_acquaintances():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 1)
    assert len(rt.history("p1")) == 1  # players observe ...
    assert rt.acquaintances("p1") == {}  # ... but only NPCs befriend


def test_nobody_befriends_themselves():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 2)
    assert "n1" not in rt.acquaintances("n1")
    assert rt.acquaintances("n1") == {}


def test_unknown_ids_stay_empty():
    _, rt = _duo(Scripted(answer()))
    assert rt.history("ghost") == []
    assert rt.acquaintances("ghost") == {}
    assert rt.export_memory("ghost") == {"short_memory": [], "long_memory": []}


def test_export_shapes_match_forge_artifacts():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 2)
    out = rt.export_memory("n2")
    assert set(out) == {"short_memory", "long_memory"}
    assert len(out["short_memory"]) == 2
    assert set(out["short_memory"][0]) == {"text", "tags"}
    assert len(out["long_memory"]) == 1
    fact = out["long_memory"][0]
    assert set(fact) == {"fact", "tags"}
    assert "n1" in fact["fact"] and "warm" in fact["fact"]


def test_read_apis_survive_close():
    _, rt = _duo(Scripted(answer(actions=[("wave", {})])))
    _act(rt, "n1", 1)
    rt.close()
    assert len(rt.history("n2")) == 1
    assert rt.acquaintances("n2")["n1"]["interactions"] == 1
    assert len(rt.export_memory("n2")["short_memory"]) == 1


def test_acquaintance_table_is_bounded():
    watchers = [m.NPC(id="watcher", position=(0.0, 0.0), horizon=1000.0,
                      implication=0.5)]
    actors = [m.NPC(id="a%02d" % i, position=(float(i), 0.0), horizon=1.0,
                    implication=0.5) for i in range(70)]
    scenario, rt = make_world(Scripted(answer(actions=[("wave", {})])),
                              players=[], npcs=watchers + actors)
    rt.registry.register("wave", {}, 0.0, lambda s, n, p: None)
    for i in range(70):
        rt.submit(m.Event(kind="tick", npc_id="a%02d" % i))
    drain(rt, 70)
    friends = rt.acquaintances("watcher")
    assert len(friends) <= 64
    assert all(v["interactions"] >= 1 for v in friends.values())
