"""npc_cortex.forge: the NPC generator.

Contracts in, finished NPCs out::

    game-description.toml + game-quest-<n>.toml
        -> rubric gate (clarity/unambiguity, refuses to proceed on FAIL)
        -> NPCGenerator (defined + generic NPCs, per-time/location/scenario)
        -> NPCSpec set + story.md/skills.md/memory JSONs + skill-<type>.md
        -> advisor (model/latency/cost per scenario + npc-type)

End-user LLM keys are acquired and held through :mod:`keys` (protected:
env/file-0600/prompt, never logged, header-only on the wire).
"""

from __future__ import annotations

from .advisor import TierAdvice, advise
from .generator import GenerationReport, NPCGenerator, prompt_context
from .keys import (KEY_ENV, LEGACY_KEY_ENV, KeyVault, acquire_key, fingerprint,
                   redact, resolve_key, store_key)
from .names import pick_name
from .profiles import PROFILES, profile, profile_title
from .rubric import PASS_SCORE, RubricReport, UnclearContract, evaluate
from .schemas import ContractError, Game, Quest, QuestNPC, load_game, load_quest
from .skill import check_actions, render_skill_file
from .spec import LOCALIZATION_LABELS, NPCSpec, SpecError

__all__ = [
    "TierAdvice", "advise", "GenerationReport", "NPCGenerator",
    "prompt_context", "KEY_ENV", "LEGACY_KEY_ENV", "KeyVault", "acquire_key", "fingerprint",
    "redact", "resolve_key", "store_key", "pick_name", "PROFILES",
    "profile", "profile_title", "PASS_SCORE", "RubricReport",
    "UnclearContract", "evaluate", "ContractError", "Game", "Quest",
    "QuestNPC", "load_game", "load_quest", "check_actions",
    "render_skill_file", "NPCSpec", "SpecError", "LOCALIZATION_LABELS",
]
