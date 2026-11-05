"""Core conformance: the engine-agnostic runtime keeps the original contract.

Compact pin of the behaviours every adapter relies on (validity, gating,
order, audit shape, close, capacity) plus the one deliberate extension:
3D positions.
"""

import pytest

import npc_cortex as m
from conftest import Scripted, answer, drain, make_world


def test_valid_answer_delivers_speech_and_applies_action():
    fired = []
    _, rt = make_world(Scripted(answer(speech="hi", actions=[("wave", {})])))
    rt.registry.register("wave", {}, 0.0,
                         lambda s, n, p: fired.append(n.id))
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    drain(rt, 1)
    assert rt.gateway.delivered == [("p1", "hi")]
    assert fired == ["n1"]
    assert rt.audit.records[0]["kind"] == "action_accepted"


def test_invalid_answer_applies_nothing_and_audits():
    _, rt = make_world(Scripted('{"speech": "oops"}'))
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    drain(rt, 1)
    assert rt.gateway.delivered == []
    assert [r["kind"] for r in rt.audit.records] == ["invalid_answer"]


def test_zero_implication_gates_without_provider_call():
    provider = Scripted(answer(speech="hi"))
    _, rt = make_world(
        provider,
        npcs=[m.NPC(id="n1", position=(1.0, 0.0), horizon=50.0, implication=0.0)],
    )
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    assert drain(rt, 1) is None
    assert provider.calls == 0
    assert rt.gateway.delivered == []


def test_events_resolve_in_submission_order():
    _, rt = make_world(Scripted(answer(speech="a"), answer(speech="b")))
    rt.submit(m.Event(kind="tick", npc_id="n1", text="1"))
    rt.submit(m.Event(kind="tick", npc_id="n1", text="2"))
    drain(rt, 2)
    assert [t for _, t in rt.gateway.delivered] == ["a", "b"]


def test_3d_positions_perceive_by_euclidean_distance():
    provider = Scripted(answer(speech="yo"))
    _, rt = make_world(
        provider,
        players=[m.Player(id="p1", role="s", position=(0.0, 0.0, 0.0),
                          horizon=5.0, online=True)],
        npcs=[m.NPC(id="n1", position=(3.0, 4.0, 0.0), horizon=50.0,
                    implication=0.5)],
    )
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    drain(rt, 1)
    assert rt.gateway.delivered == [("p1", "yo")]  # distance exactly 5


def test_3d_out_of_range_hears_nothing():
    _, rt = make_world(
        Scripted(answer(speech="yo")),
        players=[m.Player(id="p1", role="s", position=(0.0, 0.0, 0.0),
                          horizon=4.9, online=True)],
        npcs=[m.NPC(id="n1", position=(3.0, 4.0, 12.0), horizon=50.0,
                    implication=0.5)],
    )
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    drain(rt, 1)
    assert rt.gateway.delivered == []  # distance 13 > 4.9


def test_2d_behaviour_unchanged_by_3d_support():
    from npc_cortex.geometry import distance
    assert distance((0, 0), (3, 4)) == pytest.approx(5.0)
    assert distance((0, 0), (3, 4, 0)) == pytest.approx(5.0)
    assert distance((0, 0, 0), (1, 2, 2)) == pytest.approx(3.0)


def test_close_contract():
    _, rt = make_world(Scripted(answer()))
    rt.close()
    with pytest.raises(m.Closed):
        rt.submit(m.Event(kind="tick", npc_id="n1"))
    with pytest.raises(m.Closed):
        rt.pump()
    rt.cancel("engagement-1")  # inert, never raises
    assert rt.observations("n1") == []


def test_capacity_raises_overloaded():
    provider = Scripted(answer(), delay=5.0)
    _, rt = make_world(provider, capacity=1, call_timeout=30.0)
    rt.submit(m.Event(kind="tick", npc_id="n1"))
    with pytest.raises(m.Overloaded):
        rt.submit(m.Event(kind="tick", npc_id="n1"))
    rt.close()


def test_public_api_still_exported():
    for name in ("Player", "NPC", "Scenario", "Event", "ActionRegistry",
                 "Gateway", "AuditLog", "HttpProvider", "Runtime", "attach"):
        assert hasattr(m, name), name
