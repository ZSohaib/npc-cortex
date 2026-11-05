"""Rubric gate tests: examples pass; ambiguity fails loudly."""

from pathlib import Path

import pytest

from npc_cortex.forge.rubric import PASS_SCORE, evaluate
from npc_cortex.forge.schemas import ContractError, load_game, load_quest

ROOT = Path(__file__).resolve().parent.parent.parent
FORGE_EXAMPLES = ROOT / "examples" / "forge"


@pytest.mark.parametrize("setting", ["medieval", "scifi"])
def test_shipped_examples_pass_with_zero_errors(setting):
    game = load_game(FORGE_EXAMPLES / setting / "game-description.toml")
    quest = load_quest(FORGE_EXAMPLES / setting / "game-quest-1.toml")
    report = evaluate(game, quest)
    assert report.errors == [], str(report)
    assert report.passed and report.score >= PASS_SCORE


GAME_TOML = """\
[game]
title = "T"
setting = "modern"
languages = ["common"]

[locations.here]
coords = [0, 0]
description = "Here place."

[npc_types.folk]
description = "Folk."
open = [%s]
"""

ALL_OPEN = ", ".join('"%s"' % f for f in (
    "name", "age", "gender", "profile", "intellect", "languages",
    "localization", "localization_range", "body", "wealth", "social_rank",
    "power", "health", "story", "skills", "short_memory", "long_memory"))

QUEST_TOML = """\
[quest]
id = "q"
title = "Q"
scenario = "Alf wants the crown because the king fears Alf and the court watches where the guards march when dusk falls over the restless and hungry city below today tonight for sure."
time = "Dusk"

[[npc]]
id = "a"
type = "folk"
location = "here"
%s
"""


def _load(tmp_path, game_open=ALL_OPEN, npc_extra=""):
    game_file = tmp_path / "game-description.toml"
    quest_file = tmp_path / "game-quest-1.toml"
    game_file.write_text(GAME_TOML % game_open)
    quest_file.write_text(QUEST_TOML % npc_extra)
    return load_game(game_file), load_quest(quest_file)


def test_minimal_contract_passes(tmp_path):
    game, quest = _load(tmp_path)
    report = evaluate(game, quest)
    assert report.passed, str(report)


def test_field_neither_fixed_nor_open_is_an_error(tmp_path):
    game_open = ALL_OPEN.replace('"health", ', "")
    game, quest = _load(tmp_path, game_open=game_open)
    report = evaluate(game, quest)
    assert not report.passed
    assert any("neither fixed nor open" in e and "health" in e
               for e in report.errors)


def test_unknown_location_fails(tmp_path):
    game, _ = _load(tmp_path)
    text = (tmp_path / "game-quest-1.toml").read_text()
    text = text.replace('location = "here"', 'location = "nowhere"')
    (tmp_path / "game-quest-1.toml").write_text(text)
    quest = load_quest(tmp_path / "game-quest-1.toml")
    report = evaluate(game, quest)
    assert not report.passed
    assert any("unknown location" in e for e in report.errors)


def test_location_may_never_be_open(tmp_path):
    game_open = ALL_OPEN + ', "location"'
    game, quest = _load(tmp_path, game_open=game_open)
    report = evaluate(game, quest)
    assert not report.passed
    assert any("must be fixed, never open" in e for e in report.errors)


def test_wandering_with_zero_range_fails(tmp_path):
    extra = "localization = 0\nlocalization_range = 0.0"
    game, quest = _load(tmp_path, npc_extra=extra)
    report = evaluate(game, quest)
    assert not report.passed
    assert any("localization_range > 0" in e for e in report.errors)


def test_unknown_profile_fails(tmp_path):
    game, quest = _load(tmp_path, npc_extra='profile = "P99"')
    report = evaluate(game, quest)
    assert not report.passed
    assert any("unknown profile" in e for e in report.errors)


def test_thin_scenario_warns_but_can_still_pass(tmp_path):
    game_file = tmp_path / "game-description.toml"
    quest_file = tmp_path / "game-quest-1.toml"
    game_file.write_text(GAME_TOML % ALL_OPEN)
    long_brief = "Alf wants the crown because the king fears Alf and the court watches where the guards march when dusk falls over the restless and hungry city below today tonight for sure."
    quest_file.write_text((QUEST_TOML % "").replace(long_brief, "Alf walks."))
    game, quest = load_game(game_file), load_quest(quest_file)
    report = evaluate(game, quest)
    assert any("thin" in w for w in report.warnings)
    assert report.score < 100  # warnings cost points ...
    assert report.passed  # ... but never fail alone


def test_missing_tables_are_contract_errors(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[game]\ntitle = 'x'\n")
    with pytest.raises(ContractError):
        load_game(bad)
    with pytest.raises(ContractError):
        load_quest(bad)
    with pytest.raises(ContractError):
        load_game(tmp_path / "missing.toml")
