"""Advisor tests: one tiered record per (scenario, npc-type)."""

from pathlib import Path

from npc_cortex.forge.advisor import TIERS, advise
from npc_cortex.forge.generator import NPCGenerator
from npc_cortex.forge.schemas import load_game, load_quest
from npc_cortex.forge.spec import NPCSpec

ROOT = Path(__file__).resolve().parent.parent.parent
MEDIEVAL = ROOT / "examples" / "forge" / "medieval"


def _quest(**over):
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    for key, value in over.items():
        setattr(quest, key, value)
    return game, quest


def _spec(intellect=3):
    return NPCSpec(id="x", npc_type="merchant", name="X", age=30,
                   gender="female", profile="P11", intellect=intellect,
                   languages=["common"], location="market", story="S",
                   skills=[{"name": "s", "description": "d"}],
                   body={"state": "healthy", "detail": ""})


def test_calm_crowd_gets_swift():
    game, quest = _quest(dialogue_intensity="low", latency_budget_ms=5000)
    (advice,) = [a for a in advise(game, [quest], {("q1", "guard"): [_spec(2)]})
                 if a.npc_type == "guard"]
    assert advice.tier == "swift"
    assert advice.example_models == TIERS["swift"]["examples"]
    assert advice.max_attempts == 2


def test_demanding_flagship_gets_deep_with_room():
    game, quest = _quest(dialogue_intensity="high", latency_budget_ms=8000)
    game.cost_tier = "high"
    (advice,) = [a for a in advise(game, [quest], {("q1", "merchant"): [_spec(5)]})
                 if a.npc_type == "merchant"]
    assert advice.tier == "deep"
    assert advice.call_timeout <= 2.0


def test_tight_latency_budget_downgrades_with_warning():
    game, quest = _quest(dialogue_intensity="high", latency_budget_ms=600)
    (advice,) = [a for a in advise(game, [quest], {("q1", "merchant"): [_spec(5)]})
                 if a.npc_type == "merchant"]
    assert advice.tier == "swift"
    assert any("latency budget" in w for w in advice.warnings)
    assert advice.call_timeout < 1.0


def test_low_cost_tier_flags_expensive_taste():
    game, quest = _quest(dialogue_intensity="high", latency_budget_ms=8000)
    game.cost_tier = "low"
    (advice,) = [a for a in advise(game, [quest], {("q1", "merchant"): [_spec(4)]})
                 if a.npc_type == "merchant"]
    assert advice.tier in ("balanced", "deep")
    assert any("cost tier" in w for w in advice.warnings)


def test_covers_every_type_in_every_quest(tmp_path):
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    report = NPCGenerator(game, [quest]).run(tmp_path)
    grouped = {}
    for spec in report.npcs:
        grouped.setdefault((spec.context["quest"], spec.npc_type), []).append(spec)
    advice = advise(game, [quest], grouped)
    assert sorted((a.quest_id, a.npc_type) for a in advice) == [
        ("q1", "guard"), ("q1", "merchant")]
    assert all(a.rationale for a in advice)
