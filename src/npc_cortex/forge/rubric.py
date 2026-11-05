"""Evaluation rubric #1: the TOML clarity gate.

Scores a ``(Game, Quest)`` pair on clearness and unambiguity **before**
any generation happens. The generator refuses to proceed unless the
report passes. Scoring (100 points):

* ``schema`` (25): files parse, required tables/keys exist, value shapes
  hold (bad shapes are errors, not warnings).
* ``coverage`` (25): every NPC field is either fixed or explicitly
  ``open`` -- nothing may fall through silently.
* ``references`` (20): locations, languages, types, and profiles all
  resolve to something the game defines.
* ``consistency`` (15): no contradictions (wandering with zero range,
  out-of-range numbers, unknown ``open`` fields, ``location`` left open).
* ``clarity`` (15): the scenario brief and descriptions are specific
  enough to generate from (length + concrete-detail heuristics).

``PASS`` requires **zero errors and score >= 80**. Warnings (e.g. a thin
scenario brief) cost points but never fail alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .profiles import PROFILES
from .schemas import COVERED_FIELDS
from .spec import GENERATABLE_FIELDS

__all__ = ["RubricReport", "UnclearContract", "evaluate", "PASS_SCORE"]

PASS_SCORE = 80

_OPENABLE = set(GENERATABLE_FIELDS) | {"localization"}

_TYPE_HINTS = ("because", "when", "where", "wants", "needs", "fears",
               "owes", "serves", "guards", "hunts", "trades", "rules")


@dataclass
class RubricReport:
    passed: bool
    score: int
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)
    per_npc: dict = field(default_factory=dict)  # id -> {"fixed": [...], "open": [...]}

    def raise_unless_passed(self) -> None:
        if not self.passed:
            raise UnclearContract(str(self))

    def __str__(self) -> str:
        lines = ["rubric: %s (%d/100)" % ("PASS" if self.passed else "FAIL", self.score)]
        for error in self.errors:
            lines.append("  error: " + error)
        for warning in self.warnings:
            lines.append("  warning: " + warning)
        return "\n".join(lines)


class UnclearContract(Exception):
    """The TOML contract failed the clarity gate; fix it, then regenerate."""


def evaluate(game, quest) -> RubricReport:
    """Score a ``(Game, Quest)`` pair; never raises for content problems."""
    errors, warnings = [], []
    schema_pts, coverage_pts, refs_pts, consist_pts, clarity_pts = 25, 25, 20, 15, 15
    per_npc = {}

    # -- quest-level references ----------------------------------------
    if quest.dialogue_intensity not in ("low", "medium", "high"):
        errors.append("[quest].dialogue_intensity must be low|medium|high")
        schema_pts -= 5
    if not isinstance(quest.latency_budget_ms, int) or quest.latency_budget_ms <= 0:
        errors.append("[quest].latency_budget_ms must be a positive int")
        schema_pts -= 5
    if game.cost_tier not in ("low", "medium", "high"):
        errors.append("[generation].cost_tier must be low|medium|high")
        schema_pts -= 5
    seen_ids = set()
    for npc in quest.npcs:
        if npc.id in seen_ids:
            errors.append("duplicate [[npc]] id %r" % npc.id)
            schema_pts -= 5
        seen_ids.add(npc.id)

    # -- per-NPC accounting ---------------------------------------------
    for npc in quest.npcs:
        gtype = game.types.get(npc.type)
        if gtype is None:
            errors.append("npc %r: unknown type %r (game defines: %s)"
                          % (npc.id, npc.type, sorted(game.types)))
            refs_pts -= 5
            continue
        fixed = dict(gtype.fixed)
        fixed.update(npc.fixed)
        declared_open = set(gtype.open) | set(npc.open)
        opened = declared_open - set(fixed)
        per_npc[npc.id] = {"fixed": sorted(fixed), "open": sorted(opened)}

        unknown_open = sorted(f for f in opened if f not in _OPENABLE)
        if unknown_open:
            errors.append("npc %r: cannot generate %s (not generatable)"
                          % (npc.id, unknown_open))
            consist_pts -= 5
        if "location" in declared_open:
            errors.append("npc %r: 'location' must be fixed, never open "
                          "(every NPC spawns somewhere definite)" % npc.id)
            consist_pts -= 5
        missing = [f for f in COVERED_FIELDS
                   if f not in fixed and f not in opened]
        if missing:
            errors.append("npc %r: neither fixed nor open: %s "
                          "(fix the value or list it in open = [...])"
                          % (npc.id, missing))
            coverage_pts -= 8

        # references + value shapes on the fixed side
        if "location" in fixed and fixed["location"] not in game.locations:
            errors.append("npc %r: unknown location %r (game defines: %s)"
                          % (npc.id, fixed["location"], sorted(game.locations)))
            refs_pts -= 4
        for lang in (fixed.get("languages") or []):
            if lang not in game.languages:
                errors.append("npc %r: unknown language %r (game defines: %s)"
                              % (npc.id, lang, game.languages))
                refs_pts -= 4
        if "profile" in fixed and str(fixed["profile"]).upper() not in PROFILES:
            errors.append("npc %r: unknown profile %r (want P00..P15)"
                          % (npc.id, fixed["profile"]))
            refs_pts -= 4
        problems = _fixed_problems(npc.id, fixed)
        for problem in problems:
            errors.append(problem)
            consist_pts -= 3

    # -- clarity heuristics ----------------------------------------------
    scenario_words = len(quest.scenario.split())
    if scenario_words < 30:
        warnings.append("scenario brief is thin (%d words); name the place, "
                        "the stakes, and who wants what" % scenario_words)
        clarity_pts -= 7
    if not any(hint in quest.scenario.lower() for hint in _TYPE_HINTS):
        warnings.append("scenario brief states no motive or relation "
                        "(no because/wants/fears/...); generated stories will be flat")
        clarity_pts -= 5
    for name, loc in game.locations.items():
        if not loc["description"]:
            warnings.append("location %r has no description; open-field "
                            "stories cannot ground there" % name)
            clarity_pts -= 2
    for name, place in game.places.items():
        if not place.description:
            warnings.append("place %r has no description; NPCs nearby "
                            "cannot know what it is" % name)
            clarity_pts -= 2
        if not place.public and not place.owner:
            warnings.append("private place %r names no owner; ownership "
                            "questions have no answer" % name)
            clarity_pts -= 1
    for name, gtype in game.types.items():
        if not gtype.description:
            warnings.append("npc type %r has no description" % name)
            clarity_pts -= 1

    categories = {
        "schema": max(0, schema_pts), "coverage": max(0, coverage_pts),
        "references": max(0, refs_pts), "consistency": max(0, consist_pts),
        "clarity": max(0, clarity_pts),
    }
    score = sum(categories.values())
    passed = not errors and score >= PASS_SCORE
    return RubricReport(passed=passed, score=score, errors=errors,
                        warnings=warnings, categories=categories, per_npc=per_npc)


def _fixed_problems(npc_id, fixed) -> list:
    problems = []
    age = fixed.get("age")
    if age is not None and (not isinstance(age, int) or age < 0):
        problems.append("npc %r: age must be an int >= 0" % npc_id)
    intellect = fixed.get("intellect")
    if intellect is not None and intellect not in (1, 2, 3, 4, 5):
        problems.append("npc %r: intellect must be 1..5" % npc_id)
    localization = fixed.get("localization", 1)
    if localization not in (0, 1, 2):
        problems.append("npc %r: localization must be 0 (wandering), 1 (fixed) "
                        "or 2 (rooted)" % npc_id)
    loc_range = fixed.get("localization_range", 0)
    if not isinstance(loc_range, (int, float)) or loc_range < 0:
        problems.append("npc %r: localization_range must be a number >= 0" % npc_id)
    elif localization == 0 and loc_range <= 0:
        problems.append("npc %r: wandering needs localization_range > 0" % npc_id)
    body = fixed.get("body")
    if body is not None:
        state = body.get("state") if isinstance(body, dict) else body
        if state not in ("healthy", "handicapped"):
            problems.append("npc %r: body.state must be healthy|handicapped" % npc_id)
    for key in ("wealth", "social_rank", "power", "health"):
        value = fixed.get(key)
        if value is not None and (not isinstance(value, int) or not 0 <= value <= 100):
            problems.append("npc %r: %s must be an int 0..100" % (npc_id, key))
    for key in ("name", "gender"):
        value = fixed.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            problems.append("npc %r: %s must be a non-empty string" % (npc_id, key))
    skills = fixed.get("skills")
    if skills is not None and (
            not isinstance(skills, list) or not skills
            or any(not isinstance(s, dict) or not s.get("name") for s in skills)):
        problems.append("npc %r: skills must be a non-empty list of {name, ...}"
                        % npc_id)
    story = fixed.get("story")
    if story is not None and (not isinstance(story, str) or not story.strip()):
        problems.append("npc %r: story must be a non-empty string" % npc_id)
    return problems
