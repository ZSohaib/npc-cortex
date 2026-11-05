"""Profile tests: exactly 16, stable ids, setting titles."""

import pytest

from npc_cortex.forge.profiles import PROFILES, profile, profile_title


def test_exactly_sixteen_profiles():
    assert sorted(PROFILES) == ["P%02d" % i for i in range(16)]


def test_axes_cover_four_binary_choices():
    seen = set()
    for pid in PROFILES:
        rec = profile(pid)
        assert len(rec["axes"]) == 4
        seen.add(rec["axes"])
    assert len(seen) == 16  # every combination distinct


def test_titles_follow_the_setting():
    assert profile_title("P00", "medieval") == "Oathkeeper"
    assert profile_title("P00", "scifi") == "Pathfinder"
    assert profile_title("P00", "modern") == "Organizer"
    # unknown setting falls back to the neutral name, never invents one
    assert profile_title("P00", "noir") == profile("P00")["name"]


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        profile("P99")
