"""Generator tests: defined + generic NPCs, determinism, cache, LLM path."""

import json
from pathlib import Path

import pytest

from npc_cortex import ActionRegistry
from npc_cortex.forge.generator import NPCGenerator, prompt_context
from npc_cortex.forge.rubric import UnclearContract
from npc_cortex.forge.schemas import load_game, load_quest

ROOT = Path(__file__).resolve().parent.parent.parent
MEDIEVAL = ROOT / "examples" / "forge" / "medieval"


def _gen(tmp_path, provider=None, seed=7, registry=None):
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    return NPCGenerator(game, [quest], provider=provider, seed=seed,
                        registry=registry)


def test_run_writes_artifacts_and_valid_specs(tmp_path):
    report = _gen(tmp_path).run(tmp_path / "out")
    assert sorted(s.id for s in report.npcs) == ["brom", "mira"]
    for spec in report.npcs:
        spec.validate()  # written specs are always valid
        patru = tmp_path / "out" / "q1" / spec.id
        for name in ("story.md", "skills.md", "short-memory.json",
                     "long-memory.json", "awareness.md"):
            assert (patru / name).exists(), name
    assert set(report.skill_files) == {"merchant", "guard"}


def test_defined_keeps_authored_fields_generic_fills_rest(tmp_path):
    report = _gen(tmp_path).run(tmp_path / "out")
    mira = report.by_id("mira")
    assert mira.name == "Mira Fairwind"  # fixed wins
    assert mira.provenance["name"] == "fixed"
    assert "stocks" in mira.story
    brom = report.by_id("brom")
    assert brom.provenance["name"] == "template"  # generic fills
    assert brom.location == "gate" and brom.localization == 0
    assert brom.localization_range > 0  # wandering guard patrols
    assert mira.context["time"] == "Harvest eve, dusk"
    assert "tithe" in mira.context["scenario"].lower()  # per-scenario grounding


def test_deterministic_bytes_for_same_seed(tmp_path):
    _gen(tmp_path).run(tmp_path / "a")
    _gen(tmp_path).run(tmp_path / "b")
    for rel in ("q1/mira/story.md", "q1/brom/story.md",
                "q1/mira/skills.md", "skill-merchant.md"):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_cache_skips_unchanged_npcs(tmp_path):
    gen = _gen(tmp_path)
    out = tmp_path / "out"
    first = gen.run(out)
    assert first.skipped == []
    second = _gen(tmp_path).run(out)
    assert sorted(second.skipped) == ["q1/brom", "q1/mira"]
    assert second.npcs == []
    third = _gen(tmp_path).run(out, refresh=True)
    assert third.skipped == [] and len(third.npcs) == 2


def test_unclear_contract_refuses(tmp_path):
    gen = _gen(tmp_path)
    quest = gen.quests[0]
    quest.npcs[0].fixed["location"] = "nowhere"
    with pytest.raises(UnclearContract):
        gen.run(tmp_path / "out")


class _ScriptedLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        assert "q1" in prompt or "mira" in prompt or "tithe" in prompt.lower()
        return self.reply


def test_llm_fills_open_fields_with_provenance(tmp_path):
    reply = json.dumps({
        "name": "Brom Ironside", "age": 41, "gender": "male", "profile": "P05",
        "intellect": 2, "languages": ["common"], "localization_range": 9.0,
        "body": {"state": "healthy", "detail": ""}, "wealth": 30,
        "social_rank": 40, "power": 65, "health": 90,
        "story": "Brom has held the gate for a decade.",
        "skills": [{"name": "Gate watch", "description": "Sees every cart."}],
        "short_memory": [{"text": "Shook down a cart.", "tags": ["toll"]}],
        "long_memory": [{"fact": "Fears the captain.", "tags": ["duty"]}],
    })
    provider = _ScriptedLLM(reply)
    report = _gen(tmp_path, provider=provider).run(tmp_path / "out")
    brom = report.by_id("brom")
    assert brom.name == "Brom Ironside"
    assert brom.provenance["story"] == "llm"
    assert provider.calls == 2  # at most one LLM call per NPC


def test_invalid_llm_values_fall_back_to_template(tmp_path):
    provider = _ScriptedLLM("not json at all")
    report = _gen(tmp_path, provider=provider).run(tmp_path / "out")
    brom = report.by_id("brom")
    assert brom.provenance["name"] == "template"
    brom.validate()


def test_unknown_registry_actions_surface_as_warnings(tmp_path):
    registry = ActionRegistry()
    registry.register("wave", {}, 0.0, lambda s, n, p: None)
    report = _gen(tmp_path, registry=registry).run(tmp_path / "out")
    assert any("haggle" in w for w in report.warnings)


def test_runtime_bridge_spawns_at_named_location(tmp_path):
    report = _gen(tmp_path).run(tmp_path / "out")
    game = load_game(MEDIEVAL / "game-description.toml")
    mira = report.by_id("mira").to_runtime_npc(game)
    assert mira.id == "mira" and tuple(mira.position) == (0.0, 0.0)
    brom = report.by_id("brom").to_runtime_npc(game)
    assert tuple(brom.position) == (-20.0, 6.0)


def test_prompt_context_respects_budget(tmp_path):
    report = _gen(tmp_path).run(tmp_path / "out")
    mira = report.by_id("mira")
    full = prompt_context(mira, budget_chars=100000)
    assert "Mira Fairwind" in full
    tight = prompt_context(mira, budget_chars=120)
    assert len(tight) <= 120 and tight.startswith("# Mira Fairwind")
