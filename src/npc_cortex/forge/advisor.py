"""Evaluation rubric #2: model, latency, and cost advice.

For every ``(scenario, npc-type)`` pair the advisor recommends a model
tier plus runtime settings (``call_timeout``, ``max_attempts``) from the
quest's latency budget, the game's cost tier, and how demanding the
NPCs are (intellect, dialogue intensity, scenario size).

Tiers are deliberately generic -- model names below are **examples**,
not endorsements: check current pricing and latency before shipping.
Relative ranks (1 = lowest) are illustrative, not benchmarks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["TierAdvice", "advise", "TIERS"]

TIERS = {
    "swift": {
        "rank_cost": 1, "rank_latency": 1,
        "examples": ["gpt-4o-mini", "gemini-flash", "claude-haiku"],
        "blurb": "small/fast/cheap; best for background chatter and crowds",
    },
    "balanced": {
        "rank_cost": 2, "rank_latency": 2,
        "examples": ["gpt-4o", "gemini-pro", "claude-sonnet"],
        "blurb": "mid-size; best for quest-critical dialogue with nuance",
    },
    "deep": {
        "rank_cost": 3, "rank_latency": 3,
        "examples": ["gpt-4-turbo/o1-class", "claude-opus", "gemini-ultra"],
        "blurb": "frontier; only for flagship NPCs where quality beats budget",
    },
}

_INTENSITY = {"low": 0, "medium": 1, "high": 2}


@dataclass
class TierAdvice:
    quest_id: str
    npc_type: str
    tier: str
    example_models: list = field(default_factory=list)
    call_timeout: float = 2.0
    max_attempts: int = 3
    rationale: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def __str__(self) -> str:
        return "quest %s / type %s -> %s (%s)" % (
            self.quest_id, self.npc_type, self.tier,
            "; ".join(self.rationale) or "default")


def advise(game, quests, specs_by_quest_type) -> list:
    """Return one :class:`TierAdvice` per ``(quest, npc-type)`` pair.

    ``specs_by_quest_type`` maps ``(quest_id, npc_type)`` -> list of
    ``NPCSpec`` (may be empty pre-generation; type defaults still apply).
    """
    out = []
    for quest in quests:
        types_used = sorted({n.type for n in quest.npcs})
        for npc_type in types_used:
            specs = specs_by_quest_type.get((quest.id, npc_type), [])
            out.append(_advise_one(game, quest, npc_type, specs))
    return out


def _advise_one(game, quest, npc_type, specs) -> TierAdvice:
    rationale, warnings = [], []
    top_intellect = max([s.intellect for s in specs] or [3])
    demand = top_intellect + _INTENSITY.get(quest.dialogue_intensity, 1) * 2
    if len(quest.scenario.split()) > 150:
        demand += 1
        rationale.append("long scenario brief rewards stronger models")

    # demand -> tier
    if demand >= 8:
        tier = "deep"
        rationale.append("high demand (intellect %d, %s dialogue)"
                         % (top_intellect, quest.dialogue_intensity))
    elif demand >= 5:
        tier = "balanced"
        rationale.append("medium demand (intellect %d, %s dialogue)"
                         % (top_intellect, quest.dialogue_intensity))
    else:
        tier = "swift"
        rationale.append("low demand crowd/cameo dialogue")

    # latency budget constrains upward
    budget = quest.latency_budget_ms
    if budget < 800 and tier != "swift":
        warnings.append("latency budget %dms cannot host %s; dropping to swift"
                        % (budget, tier))
        tier = "swift"
    elif budget < 2000 and tier == "deep":
        warnings.append("latency budget %dms is tight for deep; dropping to balanced"
                        % budget)
        tier = "balanced"
    call_timeout = round(min(2.0, max(0.5, budget / 1000.0 * 0.8)), 2)
    rationale.append("call_timeout %ss fits the %dms frame budget"
                     % (call_timeout, budget))

    # cost tier constrains upward
    if game.cost_tier == "low" and tier != "swift":
        warnings.append("game cost tier is low; %s advice kept but flagged: "
                        "consider swift for non-critical lines" % tier)
    elif game.cost_tier == "high" and tier == "swift" and demand >= 4:
        tier = "balanced"
        rationale.append("high cost tier buys headroom: balanced")

    max_attempts = 2 if tier == "swift" else 3
    if budget < 1200:
        max_attempts = min(max_attempts, 2)
        rationale.append("few attempts fit the frame budget")
    return TierAdvice(
        quest_id=quest.id, npc_type=npc_type, tier=tier,
        example_models=list(TIERS[tier]["examples"]),
        call_timeout=call_timeout, max_attempts=max_attempts,
        rationale=rationale, warnings=warnings)
