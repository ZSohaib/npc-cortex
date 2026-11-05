"""NPC specification: the generator's output record.

Every generated NPC carries exactly the contracted fields::

    id, npc_type, name, age, gender, profile, intellect, languages,
    location, localization, localization_range, body, wealth,
    social_rank, power, health, story, skills, short_memory, long_memory

plus ``provenance`` (``fixed`` | ``template`` | ``llm`` per field), the
generation ``context`` (time, location, scenario), and computed
``awareness`` ({place_id: familiarity + known facts}). ``localization``
is spatial anchoring -- ``0`` wandering within ``localization_range``,
``1`` fixed at ``location``, ``2`` rooted there (deep local knowledge)
-- not l10n.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .profiles import PROFILES, profile_title

__all__ = ["NPCSpec", "SpecError", "SPEC_FIELDS", "INTELLECT_LABELS",
           "LOCALIZATION_LABELS", "GENERATABLE_FIELDS"]

#: Fields the contract requires on every NPC.
SPEC_FIELDS = (
    "id", "npc_type", "name", "age", "gender", "profile", "intellect",
    "languages", "location", "localization", "localization_range", "body",
    "wealth", "social_rank", "power", "health", "story", "skills",
    "short_memory", "long_memory",
)

#: Fields the LLM/template filler may generate when marked ``open``.
GENERATABLE_FIELDS = (
    "name", "age", "gender", "profile", "intellect", "languages",
    "localization_range", "body", "wealth", "social_rank", "power",
    "health", "story", "skills", "short_memory", "long_memory",
)

INTELLECT_LABELS = {
    1: "instinctive", 2: "simple", 3: "sharp", 4: "brilliant",
    5: "transcendent",
}

LOCALIZATION_LABELS = {0: "wandering", 1: "fixed", 2: "rooted"}


class SpecError(Exception):
    """An NPC record violates the contract."""


@dataclass
class NPCSpec:
    id: str
    npc_type: str
    name: str = ""
    age: int = 30
    gender: str = ""
    profile: str = "P11"
    intellect: int = 3
    languages: list = field(default_factory=list)
    location: str = ""
    localization: int = 1
    localization_range: float = 0.0
    body: dict = field(default_factory=dict)   # {"state": healthy|handicapped, "detail": str}
    wealth: int = 50
    social_rank: int = 50
    power: int = 50
    health: int = 100
    story: str = ""
    skills: list = field(default_factory=list)  # [{"name":, "description":}]
    short_memory: list = field(default_factory=list)  # [{"text":, "tags": [...]}]
    long_memory: list = field(default_factory=list)   # [{"fact":, "tags": [...]}]
    provenance: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)  # {"quest":, "time":, ...}
    awareness: dict = field(default_factory=dict)  # {place_id: {...}}, computed

    # -- validation ---------------------------------------------------

    def validate(self) -> None:
        problems = []
        if not self.id or not isinstance(self.id, str):
            problems.append("id must be a non-empty string")
        if not self.npc_type or not isinstance(self.npc_type, str):
            problems.append("npc_type must be a non-empty string")
        if not self.name or not isinstance(self.name, str):
            problems.append("name must be a non-empty string")
        if not isinstance(self.age, int) or self.age < 0:
            problems.append("age must be an int >= 0")
        if not self.gender or not isinstance(self.gender, str):
            problems.append("gender must be a non-empty string")
        if str(self.profile).upper() not in PROFILES:
            problems.append("profile must be one of %s" % sorted(PROFILES))
        if self.intellect not in INTELLECT_LABELS:
            problems.append("intellect must be 1..5")
        if (not isinstance(self.languages, list) or not self.languages
                or not all(isinstance(x, str) and x for x in self.languages)):
            problems.append("languages must be a non-empty list of strings")
        if not self.location or not isinstance(self.location, str):
            problems.append("location must be a non-empty string")
        if self.localization not in (0, 1, 2):
            problems.append("localization must be 0 (wandering), 1 (fixed) "
                            "or 2 (rooted)")
        try:
            if float(self.localization_range) < 0:
                problems.append("localization_range must be >= 0")
        except (TypeError, ValueError):
            problems.append("localization_range must be a number >= 0")
        if self.localization == 0 and float(self.localization_range or 0) <= 0:
            problems.append("wandering NPCs (localization 0) need localization_range > 0")
        body = self.body or {}
        if body.get("state") not in ("healthy", "handicapped"):
            problems.append("body.state must be 'healthy' or 'handicapped'")
        for key in ("wealth", "social_rank", "power", "health"):
            value = getattr(self, key)
            if not isinstance(value, int) or not 0 <= value <= 100:
                problems.append("%s must be an int 0..100" % key)
        if not isinstance(self.story, str) or not self.story.strip():
            problems.append("story must be a non-empty string")
        if (not isinstance(self.skills, list) or not self.skills
                or any(not isinstance(s, dict) or not s.get("name") for s in self.skills)):
            problems.append("skills must be a non-empty list of {name, description}")
        for key in ("short_memory", "long_memory"):
            value = getattr(self, key)
            if not isinstance(value, list):
                problems.append("%s must be a list" % key)
        if not isinstance(self.awareness, dict):
            problems.append("awareness must be a dict")
        if problems:
            raise SpecError("; ".join(problems))

    # -- runtime bridge -------------------------------------------------

    def spawn_position(self, game) -> tuple:
        """Resolve ``location`` to coordinates via the game's table."""
        return game.resolve_location(self.location)

    def to_runtime_npc(self, game, horizon: float = 10.0, implication: float = 0.5):
        """Build the live ``npc_cortex.NPC`` for this spec."""
        from ..models import NPC

        return NPC(id=self.id, position=self.spawn_position(game),
                   horizon=float(horizon), implication=float(implication))

    def title(self, setting: str) -> str:
        """Setting-appropriate personality title (e.g. ``Loremaster``)."""
        return profile_title(self.profile, setting)

    # -- artifacts ------------------------------------------------------

    def to_dict(self) -> dict:
        return {key: getattr(self, key) for key in SPEC_FIELDS}

    def absorb(self, exported: dict) -> None:
        """Fold lived memory (``Runtime.export_memory``) back into this
        spec, so a played session persists into the artifacts.

        Short memory appends and keeps the newest 20; long-memory facts
        append de-duplicated by fact text. Malformed entries are
        skipped, never fatal.
        """
        for entry in (exported.get("short_memory") or []):
            if not isinstance(entry, dict) or not entry.get("text"):
                continue
            self.short_memory.append({"text": str(entry["text"]),
                                      "tags": list(entry.get("tags", []))})
        del self.short_memory[:-20]
        seen = {f.get("fact") for f in self.long_memory
                if isinstance(f, dict)}
        for entry in (exported.get("long_memory") or []):
            if not isinstance(entry, dict) or not entry.get("fact"):
                continue
            if entry["fact"] in seen:
                continue
            seen.add(entry["fact"])
            self.long_memory.append({"fact": str(entry["fact"]),
                                     "tags": list(entry.get("tags", []))})

    def write_artifacts(self, directory) -> dict:
        """Write ``story.md``/``skills.md``/memory JSONs; return paths."""
        import json
        from pathlib import Path

        self.validate()
        root = Path(directory) / self.id
        root.mkdir(parents=True, exist_ok=True)
        paths = {}
        paths["story.md"] = root / "story.md"
        paths["story.md"].write_text(self.story, encoding="utf-8")
        lines = ["# Skills -- %s (%s)" % (self.name, self.id), ""]
        for skill in self.skills:
            lines.append("## %s" % skill["name"])
            lines.append("")
            lines.append(skill.get("description", ""))
            lines.append("")
        paths["skills.md"] = root / "skills.md"
        paths["skills.md"].write_text("\n".join(lines).strip() + "\n",
                                      encoding="utf-8")
        paths["short-memory.json"] = root / "short-memory.json"
        paths["short-memory.json"].write_text(
            json.dumps({"entries": self.short_memory, "cap": 20}, indent=2),
            encoding="utf-8")
        paths["long-memory.json"] = root / "long-memory.json"
        paths["long-memory.json"].write_text(
            json.dumps({"facts": self.long_memory}, indent=2), encoding="utf-8")
        paths["awareness.md"] = root / "awareness.md"
        paths["awareness.md"].write_text(self._awareness_markdown(),
                                         encoding="utf-8")
        return {key: str(value) for key, value in paths.items()}

    def known_places(self) -> list:
        """``(place_id, entry)`` sorted by familiarity, deepest first."""
        return sorted(self.awareness.items(),
                      key=lambda item: -item[1].get("familiarity", 0))

    def _awareness_markdown(self) -> str:
        label = LOCALIZATION_LABELS.get(self.localization, "?")
        lines = ["# Awareness -- %s (%s)" % (self.name, self.id),
                 "",
                 "Home: %s. Localization: %s (%s)." % (
                     self.location, label, self.localization),
                 ""]
        if not self.awareness:
            lines.append("Knows no named places yet.")
            lines.append("")
            return "\n".join(lines)
        for pid, entry in self.known_places():
            facts = entry.get("facts", {})
            lines.append("## %s (%s, familiarity %d)" % (
                pid, facts.get("kind", "place"),
                entry.get("familiarity", 0)))
            lines.append("")
            if facts.get("description"):
                lines.append(facts["description"])
                lines.append("")
            if "owner" in facts and facts["owner"]:
                lines.append("Owner: %s." % facts["owner"])
            if facts.get("interior"):
                lines.append("Inside: %s" % facts["interior"])
            for text in facts.get("hidden", []):
                lines.append("Hidden: %s" % text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"
