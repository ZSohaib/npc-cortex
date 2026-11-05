"""skill-<npc-type>.md tests: content contract + registry check."""

from pathlib import Path

from npc_cortex import ActionRegistry
from npc_cortex.forge.generator import NPCGenerator
from npc_cortex.forge.schemas import load_game, load_quest
from npc_cortex.forge.skill import check_actions, render_skill_file

ROOT = Path(__file__).resolve().parent.parent.parent
MEDIEVAL = ROOT / "examples" / "forge" / "medieval"


def _report(tmp_path):
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    return game, NPCGenerator(game, [quest]).run(tmp_path)


def test_skill_file_contract(tmp_path):
    game, report = _report(tmp_path)
    text = Path(report.skill_files["merchant"]).read_text()
    assert text.startswith("# Skill: merchant")
    assert "mira" in text and "Emberfall" in text
    assert "haggle" in text and "wave" in text  # allowed actions listed
    assert "Memory policy" in text
    assert "Provenance" in text
    assert "Archivist" in text  # P11 medieval title for Mira's profile


def test_check_actions_splits_known_unknown():
    registry = ActionRegistry()
    registry.register("wave", {}, 0.0, lambda s, n, p: None)
    known, unknown = check_actions(["wave", "haggle"], registry)
    assert (known, unknown) == (["wave"], ["haggle"])


def test_unknown_actions_flagged_in_file(tmp_path):
    game, report = _report(tmp_path)
    registry = ActionRegistry()
    known, unknown = check_actions(game.types["merchant"].actions, registry)
    text = render_skill_file("merchant", game, report.npcs[:1],
                             quest_ids=["q1"], known_actions=known,
                             unknown_actions=unknown)
    assert "NOT in the registry" in text and "haggle" in text
