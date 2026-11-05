"""Setting-aware personal names (medieval, scifi, modern + fallback).

The generator picks names conditioned on the game's ``setting`` so a
medieval blacksmith is never called ``Zx-417`` and a station engineer is
never called ``Aldric``. Banks are deliberately small: they seed the
``template`` filler and give the LLM few-shot anchors, not an
exhaustive census.
"""

from __future__ import annotations

import random

__all__ = ["pick_name", "SETTING_NAMES"]

SETTING_NAMES = {
    "medieval": {
        "male": ["Aldric", "Brom", "Cedric", "Doran", "Edmund", "Fenwick",
                 "Garrick", "Hadrian"],
        "female": ["Elswyth", "Bryn", "Celcia", "Dunna", "Elowen", "Freya",
                   "Gisela", "Hilda"],
        "any": ["Ash", "Briar", "Clover", "Dell", "Ember", "Flint"],
        "surnames": ["Ashdown", "Blackwood", "Crowfield", "Dunmore", "Elmsworth",
                     "Fairwind", "Grimshaw", "Holloway"],
    },
    "scifi": {
        "male": ["Kael", "Dax", "Rook", "Sable", "Vex", "Corvin", "Juno", "Pax"],
        "female": ["Nova", "Lyra", "Vesper", "Io", "Senna", "Quill", "Nyx", "Ada"],
        "any": ["Echo", "Onyx", "Pixel", "Zero", "Flux", "Wren"],
        "surnames": ["Vance", "Kor", "Dray", "Sol", "Meridian", "Jax", "Halcyon", "Rook"],
    },
    "modern": {
        "male": ["Marcus", "Devon", "Ellis", "Frank", "Gabe", "Hugo", "Ivan", "Jonah"],
        "female": ["Maya", "Nina", "Olivia", "Priya", "Quinn", "Rosa", "Sofia", "Tara"],
        "any": ["Alex", "Casey", "Devon", "Emerson", "Finley", "Gray"],
        "surnames": ["Carter", "Delacroix", "Evans", "Frost", "Garcia", "Hughes",
                     "Ivers", "Jones"],
    },
}

_FALLBACK = {
    "male": ["Ashen", "Brio", "Cor", "Dain"],
    "female": ["Alba", "Bina", "Cora", "Dina"],
    "any": ["Rill", "Sable", "Tarn", "Vale"],
    "surnames": ["Ash", "Brook", "Cairn", "Dale"],
}


def pick_name(setting: str, gender: str, rng: random.Random) -> str:
    """Return ``'First Last'`` for a setting + gender (seeded via ``rng``)."""
    bank = SETTING_NAMES.get(str(setting).lower(), _FALLBACK)
    gender = str(gender).lower()
    if gender in ("male", "m", "man"):
        first = rng.choice(bank["male"])
    elif gender in ("female", "f", "woman"):
        first = rng.choice(bank["female"])
    else:
        first = rng.choice(bank["any"] + bank["male"] + bank["female"])
    return "%s %s" % (first, rng.choice(bank["surnames"]))
