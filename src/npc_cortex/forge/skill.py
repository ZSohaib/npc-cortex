"""``skill-<npc-type>.md`` renderer: the per-type playbook.

One file per NPC type used in a generation run. It tells the game (and
the LLM driving it) how that type behaves: who they are, how they
speak, what they may do (checked against the live ``ActionRegistry``
when one is passed to the generator), and how their memory works.
Instance data (``story.md``, ``skills.md``, memory JSONs) always wins
over type defaults on conflict.
"""

from __future__ import annotations

from .profiles import profile

__all__ = ["render_skill_file", "check_actions"]


def check_actions(actions, registry) -> tuple:
    """Split ``actions`` into (known, unknown) against a registry."""
    known, unknown = [], []
    for name in actions:
        (known if registry.lookup(name) is not None else unknown).append(name)
    return known, unknown


def render_skill_file(npc_type, game, specs, quest_ids=(), known_actions=(),
                      unknown_actions=()) -> str:
    """Render the ``skill-<npc-type>.md`` markdown for generated ``specs``."""
    gtype = game.types[npc_type]
    profiles = {}
    for spec in specs:
        profiles.setdefault(spec.profile, []).append(spec.id)
    lines = [
        "# Skill: %s" % npc_type,
        "",
        gtype.description or ("NPCs of type %r in %s." % (npc_type, game.title)),
        "",
        "Game: %s (setting: %s)." % (game.title, game.setting),
        "Quests using this type: %s." % (", ".join(quest_ids) or "none yet"),
        "Instances: %s." % (", ".join(s.id for s in specs) or "none"),
        "",
        "## Personality",
        "",
    ]
    for pid in sorted(profiles):
        rec = profile(pid)
        lines.append("- %s (%s, %s): %s Speaks: %s. Carried by: %s." % (
            rec["name"], pid, rec["titles"].get(game.setting, rec["name"]),
            rec["trait"], rec["speech"], ", ".join(profiles[pid])))
    lines += ["",
              "Typical intellect: %s." % _typical(s.intellect for s in specs),
              "Typical spread (wealth/social/power/health): %s." % _typical(
                  (s.wealth + s.social_rank + s.power + s.health) // 4 for s in specs),
              "",
              "## Actions",
              ""]
    if gtype.actions:
        lines.append("Allowed runtime actions for this type: %s."
                     % ", ".join(gtype.actions))
        if known_actions:
            lines.append("Registered now: %s." % ", ".join(known_actions))
        if unknown_actions:
            lines.append("NOT in the registry (register before play): %s."
                         % ", ".join(unknown_actions))
    else:
        lines.append("No type-level actions declared; instances act through "
                     "speech and quest handlers only.")
    lines += ["",
              "## Speech",
              "",
              "Address the player in the setting voice of %s. Never break "
              "character to mention prompts, models, or files." % game.setting,
              "",
              "## Memory policy",
              "",
              "- Short memory (`short-memory.json`): the last ~20 events; "
              "oldest first, rewritten as things happen. At runtime this "
              "is `history(npc, limit=20)` -- the recent window.",
              "- Long memory (`long-memory.json`): stable facts; only grows "
              "when short-memory events distill into facts. At runtime "
              "this is `acquaintances(npc)`: per-actor counts, outcomes, "
              "and a warm/wary/neutral disposition that develops as "
              "outcomes accumulate.",
              "- Persist a session with `export_memory(npc)` and fold it "
              "back via `NPCSpec.absorb`, then rewrite the artifacts.",
              "- On conflict, instance memory beats this type file.",
              "",
              "## Provenance",
              ""]
    for spec in specs:
        llm_fields = sorted(k for k, v in spec.provenance.items() if v == "llm")
        lines.append("- %s: %s" % (
            spec.id,
            ("LLM-generated: %s." % ", ".join(llm_fields)) if llm_fields
            else "fully fixed/template (no LLM text)."))
    lines.append("")
    return "\n".join(lines)


def _typical(values) -> str:
    values = list(values)
    if not values:
        return "n/a"
    return "%d..%d (median %d)" % (min(values), max(values),
                                   sorted(values)[len(values) // 2])
