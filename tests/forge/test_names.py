"""Name-bank tests: setting-appropriate, seeded, gender-aware."""

import random

from npc_cortex.forge.names import SETTING_NAMES, pick_name


def test_banks_cover_supported_settings():
    assert set(SETTING_NAMES) >= {"medieval", "scifi", "modern"}
    for bank in SETTING_NAMES.values():
        for key in ("male", "female", "any", "surnames"):
            assert len(bank[key]) >= 4, key


def test_pick_is_seeded():
    a = pick_name("medieval", "female", random.Random(3))
    b = pick_name("medieval", "female", random.Random(3))
    assert a == b and len(a.split()) == 2


def test_settings_draw_from_their_own_banks():
    rng = random.Random(11)
    medieval = {pick_name("medieval", "male", rng) for _ in range(30)}
    scifi = {pick_name("scifi", "male", rng) for _ in range(30)}
    assert medieval.isdisjoint(scifi)  # no Aldric on the station


def test_unknown_setting_falls_back_without_crashing():
    name = pick_name("noir", "nonbinary", random.Random(1))
    assert len(name.split()) == 2
