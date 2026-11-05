"""Places and environmental awareness.

NPCs know the world around them: nearby buildings and landmarks, who
owns them, what is inside -- including private interiors and hidden
details for NPCs familiar enough to know. Knowledge is gated by
**familiarity** (0..100), which grows with the NPC's ``localization``
(0 wandering, 1 fixed, 2 rooted), intellect, and nearness to home:

* anyone nearby sees a place exists (id, kind, coords, description);
* owners are known for public places, or at familiarity >= 50;
* interiors are known for public places, or at familiarity >= 60;
* each hidden detail unlocks at its own ``min_familiarity``;
* the owner always knows everything about their own place.

Fixed NPCs know their home ground; rooted ones know the hidden things.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import distance

__all__ = ["Place", "WorldMap", "familiarity", "knowledge",
           "OWNER_KNOWN_AT", "INTERIOR_KNOWN_AT", "LOCALIZATION_BASE"]

OWNER_KNOWN_AT = 50
INTERIOR_KNOWN_AT = 60

#: Familiarity base by localization: wandering / fixed / rooted.
LOCALIZATION_BASE = {0: 25, 1: 70, 2: 95}


@dataclass
class Place:
    id: str
    coords: tuple = (0.0, 0.0)
    kind: str = "place"
    description: str = ""
    owner: str = ""
    public: bool = True
    interior: str = ""
    hidden: list = field(default_factory=list)  # [{text, min_familiarity}]

    @staticmethod
    def from_dict(id: str, data: dict) -> "Place":
        coords = data.get("coords", [0, 0])
        return Place(
            id=id,
            coords=tuple(float(c) for c in coords),
            kind=str(data.get("kind", "place")),
            description=str(data.get("description", "")),
            owner=str(data.get("owner", "")),
            public=bool(data.get("public", True)),
            interior=str(data.get("interior", "")),
            hidden=[{"text": str(h.get("text", "")),
                     "min_familiarity": int(h.get("min_familiarity", 100))}
                    for h in (data.get("hidden") or [])],
        )


def familiarity(home_coords, localization: int, intellect: int,
                target_coords) -> int:
    """Familiarity (0..100) of an NPC with a place.

    ``home_coords`` is where the NPC lives (its ``location`` resolved);
    ``localization`` is 0 wandering, 1 fixed, 2 rooted. Near-home ground
    keeps the full base; farther places fade by distance band; sharper
    NPCs pick up more everywhere.
    """
    base = LOCALIZATION_BASE[int(localization)]
    span = distance(home_coords, target_coords)
    if span <= 10:
        band = 0                     # home ground
    elif span <= 30:
        band = -15                   # known district
    else:
        band = -30                   # far afield
    bonus = (int(intellect) - 3) * 3
    home = 10 if span == 0 and int(localization) >= 1 else 0
    return max(0, min(100, base + band + bonus + home))


def knowledge(place: Place, familiarity: int, is_owner: bool = False) -> dict:
    """Everything about ``place`` known at ``familiarity``.

    Always known: id, kind, coords, description, public. Owner, interior,
    and hidden details unlock by the thresholds above; owners know all.
    """
    score = max(0, min(100, int(familiarity)))
    known = {
        "id": place.id,
        "kind": place.kind,
        "coords": list(place.coords),
        "description": place.description,
        "public": bool(place.public),
    }
    if is_owner or not place.owner or place.public or score >= OWNER_KNOWN_AT:
        known["owner"] = place.owner
    if is_owner or not place.interior or place.public or score >= INTERIOR_KNOWN_AT:
        known["interior"] = place.interior
    if is_owner:
        known["hidden"] = [h["text"] for h in place.hidden]
    else:
        known["hidden"] = [h["text"] for h in place.hidden
                           if score >= int(h.get("min_familiarity", 100))]
    return known


class WorldMap:
    """Spatial index over places; powers live ``surroundings()``."""

    def __init__(self, places=()) -> None:
        self.places = list(places)

    def nearby(self, position, radius: float) -> list:
        """``[(place, distance)]`` within ``radius``, nearest first."""
        if not isinstance(radius, (int, float)) or radius < 0:
            raise ValueError("radius must be a number >= 0")
        found = [(place, distance(position, place.coords))
                 for place in self.places]
        return sorted(((p, d) for p, d in found if d <= radius),
                      key=lambda item: item[1])
