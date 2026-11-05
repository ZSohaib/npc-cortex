"""Awareness tests: TOML places -> gated per-NPC knowledge."""

from pathlib import Path

import pytest

from npc_cortex.forge.generator import NPCGenerator, prompt_context
from npc_cortex.forge.rubric import evaluate
from npc_cortex.forge.schemas import ContractError, load_game, load_quest
from npc_cortex.forge.spec import LOCALIZATION_LABELS, NPCSpec, SpecError

ROOT = Path(__file__).resolve().parent.parent.parent
MEDIEVAL = ROOT / "examples" / "forge" / "medieval"


def _loaded():
    return (load_game(MEDIEVAL / "game-description.toml"),
            load_quest(MEDIEVAL / "game-quest-1.toml"))


def test_example_places_parse():
    game, _ = _loaded()
    assert set(game.places) == {"tithe_barn", "market_well"}
    barn = game.places["tithe_barn"]
    assert barn.public is False and barn.owner == "collector_cask"
    assert barn.hidden == [{"text": "The false floor hides skimmed coin.",
                            "min_familiarity": 70}]


def test_bad_place_shapes_are_contract_errors(tmp_path):
    base = (MEDIEVAL / "game-description.toml").read_text()
    bad_coords = tmp_path / "game-description.toml"
    bad_coords.write_text(base.replace("coords = [2, 1]", "coords = [2]"))
    with pytest.raises(ContractError):
        load_game(bad_coords)
    bad_hidden = tmp_path / "game2.toml"
    bad_hidden.write_text(base.replace("min_familiarity = 70", "min_familiarity = 101"))
    with pytest.raises(ContractError):
        load_game(bad_hidden)


def test_rooted_mira_knows_the_private_barn_whole(tmp_path):
    game, quest = _loaded()
    report = NPCGenerator(game, [quest]).run(tmp_path)
    mira = report.by_id("mira")
    assert mira.localization == 2
    barn = mira.awareness["tithe_barn"]
    assert barn["familiarity"] >= 70
    assert barn["facts"]["owner"] == "collector_cask"
    assert "false floor" in barn["facts"]["interior"]
    assert barn["facts"]["hidden"] == ["The false floor hides skimmed coin."]


def test_wandering_brom_knows_facades_only(tmp_path):
    game, quest = _loaded()
    report = NPCGenerator(game, [quest]).run(tmp_path)
    brom = report.by_id("brom")
    barn = brom.awareness["tithe_barn"]
    assert barn["familiarity"] < 50
    assert "owner" not in barn["facts"]
    assert "interior" not in barn["facts"]
    assert barn["facts"]["hidden"] == []
    assert barn["facts"]["description"].startswith("Stone tithe barn")


def test_awareness_md_artifact(tmp_path):
    game, quest = _loaded()
    NPCGenerator(game, [quest]).run(tmp_path)
    text = (tmp_path / "q1" / "mira" / "awareness.md").read_text()
    assert text.startswith("# Awareness -- Mira Fairwind (mira)")
    assert "rooted (2)" in text
    assert "collector_cask" in text and "skimmed coin" in text
    brom_text = (tmp_path / "q1" / "brom" / "awareness.md").read_text()
    assert "collector_cask" not in brom_text  # wanderers don't know owners


def test_prompt_context_carries_surroundings(tmp_path):
    game, quest = _loaded()
    report = NPCGenerator(game, [quest]).run(tmp_path)
    assert "tithe_barn" in prompt_context(report.by_id("mira"))
    assert "collector_cask" in prompt_context(report.by_id("mira"))


def test_localization_rejects_out_of_range():
    assert LOCALIZATION_LABELS == {0: "wandering", 1: "fixed", 2: "rooted"}
    spec = NPCSpec(id="x", npc_type="t", name="X", age=1, gender="g",
                   profile="P00", intellect=3, languages=["c"], location="l",
                   localization=3, story="s",
                   skills=[{"name": "s", "description": "d"}],
                   body={"state": "healthy", "detail": ""})
    with pytest.raises(SpecError):
        spec.validate()
