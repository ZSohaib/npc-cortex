"""Runtime surroundings tests: live spatial sense, no leaks."""

import pytest

import npc_cortex as m
from conftest import Scripted, answer, make_world
from npc_cortex.places import Place


def _world():
    scenario, rt = make_world(Scripted(answer()))
    scenario.places = [
        Place(id="barn", coords=(2.0, 1.0), kind="building",
              description="Stone barn.", owner="cask", public=False,
              interior="Counting room.", hidden=[{"text": "Coin.", "min_familiarity": 1}]),
        Place(id="well", coords=(50.0, 0.0), kind="landmark",
              description="Old well.", public=True),
    ]
    return scenario, rt  # n1 sits at (1, 0)


def test_nearby_places_nearest_first():
    _, rt = _world()
    out = rt.surroundings("n1", radius=100.0)
    assert [p["id"] for p in out] == ["barn", "well"]
    assert out[0]["distance"] == pytest.approx(2 ** 0.5)  # n1 at (1, 0)
    assert set(out[0]) == {"id", "kind", "distance", "description", "public"}


def test_radius_filters():
    _, rt = _world()
    assert [p["id"] for p in rt.surroundings("n1", radius=5.0)] == ["barn"]
    assert rt.surroundings("n1", radius=0.5) == []


def test_private_facts_never_leak_over_surroundings():
    _, rt = _world()
    (barn,) = [p for p in rt.surroundings("n1") if p["id"] == "barn"]
    assert "owner" not in barn and "interior" not in barn and "hidden" not in barn
    assert barn["public"] is False  # visibility of privacy itself is fine


def test_unknown_npc_sees_nothing():
    _, rt = _world()
    assert rt.surroundings("ghost") == []


def test_negative_radius_rejected():
    _, rt = _world()
    with pytest.raises(ValueError):
        rt.surroundings("n1", radius=-1.0)


def test_surroundings_survives_close():
    _, rt = _world()
    rt.close()
    assert [p["id"] for p in rt.surroundings("n1", radius=5.0)] == ["barn"]
