"""Lived-memory tests: export -> absorb -> rewrite artifacts."""

import json
from pathlib import Path

import npc_cortex as m
from conftest import Scripted, answer, drain, make_world
from npc_cortex.forge.generator import NPCGenerator
from npc_cortex.forge.schemas import load_game, load_quest

ROOT = Path(__file__).resolve().parent.parent.parent
MEDIEVAL = ROOT / "examples" / "forge" / "medieval"


def _played():
    players = [m.Player(id="p1", role="s", position=(0.0, 0.0),
                        horizon=50.0, online=True)]
    npcs = [m.NPC(id="n1", position=(1.0, 0.0), horizon=50.0, implication=0.5),
            m.NPC(id="n2", position=(2.0, 0.0), horizon=50.0, implication=0.5)]
    _, rt = make_world(Scripted(answer(actions=[("wave", {})])),
                       players=players, npcs=npcs)
    rt.registry.register("wave", {}, 0.0, lambda s, n, p: None)
    for i in range(3):
        rt.submit(m.Event(kind="tick", npc_id="n1", text="t%d" % i))
    drain(rt, 3)
    return rt


def test_absorb_folds_export_back_into_a_spec(tmp_path):
    rt = _played()
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    spec = NPCGenerator(game, [quest]).run(tmp_path).by_id("mira")
    before_short, before_long = len(spec.short_memory), len(spec.long_memory)
    spec.absorb(rt.export_memory("n2"))
    assert len(spec.short_memory) == before_short + 3  # n1 waved thrice
    assert any("n1 wave" in e["text"] for e in spec.short_memory)
    assert len(spec.long_memory) == before_long + 1  # one new acquaintance
    assert "n1" in spec.long_memory[-1]["fact"]
    spec.validate()  # absorbed memory keeps the spec valid


def test_absorb_dedups_long_facts_and_caps_short(tmp_path):
    rt = _played()
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    spec = NPCGenerator(game, [quest]).run(tmp_path).by_id("brom")
    exported = rt.export_memory("n2")
    spec.absorb(exported)
    spec.absorb(exported)  # same session twice: no duplicate facts
    facts = [f["fact"] for f in spec.long_memory]
    assert len(facts) == len(set(facts))
    big = {"short_memory": [{"text": "e%d" % i, "tags": []} for i in range(50)],
           "long_memory": []}
    spec.absorb(big)
    assert len(spec.short_memory) == 20  # newest kept
    assert spec.short_memory[-1]["text"] == "e49"


def test_absorb_skips_malformed_entries(tmp_path):
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    spec = NPCGenerator(game, [quest]).run(tmp_path).by_id("brom")
    before = (len(spec.short_memory), len(spec.long_memory))
    spec.absorb({"short_memory": [{"nope": 1}, "junk", {"text": ""}],
                 "long_memory": [{"fact": ""}, None]})
    assert (len(spec.short_memory), len(spec.long_memory)) == before


def test_rewritten_artifacts_carry_lived_memory(tmp_path):
    rt = _played()
    game = load_game(MEDIEVAL / "game-description.toml")
    quest = load_quest(MEDIEVAL / "game-quest-1.toml")
    out = tmp_path / "out"
    spec = NPCGenerator(game, [quest]).run(out).by_id("brom")
    spec.absorb(rt.export_memory("n2"))
    spec.write_artifacts(out / "q1")
    short = json.loads((out / "q1" / "brom" / "short-memory.json").read_text())
    assert any("n1 wave" in e["text"] for e in short["entries"])
    long = json.loads((out / "q1" / "brom" / "long-memory.json").read_text())
    assert any("n1" in f["fact"] for f in long["facts"])
