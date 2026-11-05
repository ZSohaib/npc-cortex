"""Places tests: familiarity gradients and gated knowledge."""

import pytest

from npc_cortex.places import (Place, WorldMap, familiarity, knowledge,
                               INTERIOR_KNOWN_AT, LOCALIZATION_BASE,
                               OWNER_KNOWN_AT)


def _barn():
    return Place(
        id="barn", coords=(2.0, 1.0), kind="building",
        description="Stone barn.", owner="cask", public=False,
        interior="Counting room.", hidden=[{"text": "Skimmed coin.", "min_familiarity": 70}],
    )


def test_localization_bases_rise_with_rootedness():
    assert LOCALIZATION_BASE[0] < LOCALIZATION_BASE[1] < LOCALIZATION_BASE[2]
    home, near = (0.0, 0.0), (2.0, 1.0)
    assert familiarity(home, 0, 3, near) < familiarity(home, 1, 3, near)
    assert familiarity(home, 1, 3, near) < familiarity(home, 2, 3, near)


def test_familiarity_bands_and_clamps():
    assert familiarity((0, 0), 2, 3, (0, 0)) == 100  # rooted at home
    assert familiarity((0, 0), 1, 3, (2, 1)) == 70   # fixed, home ground
    assert familiarity((0, 0), 0, 2, (100, 0)) == 0  # far, dull, wandering
    assert familiarity((0, 0), 0, 5, (20, 0)) == 25 - 15 + 6  # district + brains


def test_strangers_see_facades_only():
    facts = knowledge(_barn(), 10)
    assert facts["description"] == "Stone barn."
    assert "owner" not in facts
    assert "interior" not in facts
    assert facts["hidden"] == []


def test_owner_and_interior_unlock_by_threshold():
    assert "owner" not in knowledge(_barn(), OWNER_KNOWN_AT - 1)
    assert knowledge(_barn(), OWNER_KNOWN_AT)["owner"] == "cask"
    assert "interior" not in knowledge(_barn(), INTERIOR_KNOWN_AT - 1)
    assert knowledge(_barn(), INTERIOR_KNOWN_AT)["interior"] == "Counting room."
    assert knowledge(_barn(), 69)["hidden"] == []
    assert knowledge(_barn(), 70)["hidden"] == ["Skimmed coin."]


def test_public_places_hide_nothing_structural():
    hall = Place(id="hall", coords=(0, 0), description="Hall.",
                 owner="town", public=True, interior="Benches.")
    facts = knowledge(hall, 0)
    assert (facts["owner"], facts["interior"]) == ("town", "Benches.")


def test_owners_know_their_own_place_whole():
    facts = knowledge(_barn(), 0, is_owner=True)
    assert facts["owner"] == "cask"
    assert facts["interior"] == "Counting room."
    assert facts["hidden"] == ["Skimmed coin."]


def test_world_map_nearby_sorted_and_bounded():
    world = WorldMap([Place(id="far", coords=(100, 0)),
                      Place(id="near", coords=(3, 4))])
    assert [(p.id, d) for p, d in world.nearby((0, 0), 50.0)] == [("near", 5.0)]
    assert world.nearby((0, 0), 500.0)[0][0].id == "near"
    with pytest.raises(ValueError):
        world.nearby((0, 0), -1.0)


def test_place_from_dict_defaults():
    place = Place.from_dict("x", {"coords": [1, 2]})
    assert place.coords == (1.0, 2.0) and place.public is True
    assert place.hidden == [] and place.owner == ""
