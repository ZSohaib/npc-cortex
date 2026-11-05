---
name: npc-generation-contract
description: Generate game NPCs from game-description.toml and game-quest TOMLs through the clarity gate.
---

# NPC Generation Contract

Turn a game developer's TOMLs into finished NPCs: validated specs,
`story.md` / `skills.md` / memory JSONs per NPC, one
`skill-<npc-type>.md` per type, and model/latency/cost advice per
scenario and type. Never generate from an unclear contract: the
evaluation skill (`skills/npc-generation-evaluation/SKILL.md`) grades
every contract and every output, and any error there sends the work
back for reiteration.

## 1. Inputs the developer provides

`game-description.toml`:

* `[game]`: `title`, `setting` (`medieval`, `scifi`, `modern`, or a new
  string + name bank, see section 2), `languages` (non-empty list),
  optional `default_horizon`, `default_implication`.
* `[time]`: `current` (the era string generation grounds on).
* `[locations.<name>]`: `coords` (`[x, y]` or `[x, y, z]`) plus a
  `description` (no description = clarity points lost).
* `[places.<id>]`: `coords`, `kind` (`building`, `landmark`, ...),
  `description`, `owner` (who the place belongs to, `""` if none),
  `public` (default true), `interior` (what is inside), `hidden`
  (`[{ text, min_familiarity }]`, 0..100). Buildings -- even private
  ones -- live here with their interiors and secrets.
* `[generation]`: `seed`, `cost_tier` (`low` | `medium` | `high`).
* `[npc_types.<type>]`: `description`, any spec field as a fixed
  default, `open = [...]` (fields the filler generates per instance),
  `actions = [...]` (allowed runtime action names).

`game-quest-<n>.toml`:

* `[quest]`: `id`, `title`, `scenario` (>= 30 words, states a motive or
  relation: because/wants/fears/...), `time` (the per-time context),
  `latency_budget_ms`, `dialogue_intensity` (`low` | `medium` | `high`).
* `[[npc]]`: `id`, `type` (must exist in the game file), `mode`
  (`defined` = mostly fixed inline, `generic` = mostly open),
  `location` (always fixed, must exist), fixed overrides, `open = [...]`
  additions. Type defaults apply underneath; NPC values win.

## 2. Personalities and names follow the setting

* Exactly 16 profiles exist (`P00`..`P15`, four axes: Drive, Heart,
  Order, Mind -- see `forge/profiles.py`). Never invent a 17th.
* Titles are setting-appropriate: the same profile renders e.g.
  `Oathkeeper` (medieval), `Pathfinder` (scifi), `Organizer` (modern).
  New settings reuse neutral names until a title row is added **with a
  test** in `tests/forge/test_profiles.py`.
* Personal names come from the setting's bank (`forge/names.py`):
  medieval NPCs get medieval names, scifi gets scifi names. New
  settings add a bank **with a test** in `tests/forge/test_names.py`.

## 3. Generation is contextual and provenance-tracked

* Every NPC resolves per-time (quest `time`), per-localization
  (its `location` + description), and per-scenario (quest brief);
  all three land in the spec's `context` and ground filler text.
* `localization` is spatial anchoring AND local knowledge: `0`
  wandering within `localization_range` (which must then be > 0), `1`
  fixed at `location`, `2` rooted there. The higher the localization,
  the deeper the awareness: familiarity (0..100) rises with it, with
  intellect, and with nearness to home (`places.familiarity`).
* Anyone nearby knows a place exists and what it looks like; owners
  unlock at familiarity >= 50 (public places always), interiors at
  >= 60, each hidden detail at its own `min_familiarity`, and owners
  always know their own place whole (`places.knowledge`). Rooted NPCs
  thus know interiors, private ownership, and buried secrets about
  their home ground; wanderers know facades.
* `body.state` is `healthy` | `handicapped` (+ optional `detail`);
  `intellect` is 1..5; `wealth`/`social_rank`/`power`/`health` are
  0..100; `languages` must come from the game's list.
* Every field's `provenance` is `fixed` (authored), `template`
  (seeded offline filler), or `llm`. Template fills deterministically
  from `seed`; LLM fills are JSON-validated per field and fall back to
  template on any invalid value. Without a provider the whole pipeline
  still runs offline.

## 4. Outputs

* Per NPC under `<out>/<quest>/<npc-id>/`: `story.md`, `skills.md`,
  `short-memory.json` (cap 20, oldest first), `long-memory.json`, and
  `awareness.md` (known places with familiarity, owners, interiors,
  and unlocked hidden details, deepest first). Specs validate
  (`NPCSpec.validate`) before anything is written.
* Per type: `skill-<npc-type>.md` -- personality, speech, allowed
  actions (checked against the live registry when provided; unknown
  names are reported, never silently kept), memory policy, provenance.
  Instance data beats the type file on conflict.
* A `manifest.json` fingerprints every contract: unchanged NPCs are
  skipped on re-runs (override with `refresh=True`).
* Memory develops in play and round-trips through artifacts:
  `history(npc[, actor, limit])` is the specific shared record trail
  (short-term = recent window), `acquaintances(npc)` the distilled
  per-actor knowledge (counts, outcomes, warm/wary/neutral
  disposition), `export_memory(npc)` the forge-shaped snapshot, and
  `NPCSpec.absorb` folds a session back before artifacts are
  rewritten. Seed memories in TOML; never hand-edit developed ones.

## 5. End-user API keys stay protected

Resolution: `NPC_CORTEX_API_KEY` env (`NPC_LLM_API_KEY` as pre-rename fallback), then `~/.npc_cortex/key` (refused
unless `0600`), then an interactive `getpass` prompt with optional
`0600` persist (`forge.keys.acquire_key`). Never print or log a key
(`fingerprint` shows `...last4`; `redact` scrubs text); on the wire it
travels header-only, never in a body. No other acquisition path is
allowed without updating this contract and its tests.

## 6. Efficiency rules

* Seeded RNG everywhere: same contracts + seed = byte-identical NPCs.
* Manifest cache skips unchanged NPCs; generation is per quest and
  skips cached NPCs instead of re-running the whole game.
* Lore entering prompts goes through `prompt_context(spec,
  budget_chars)` so long stories/memories cannot blow latency or
  memory; oldest short-memory and trailing story text cut first.
* The filler makes at most **one** LLM call per NPC (single JSON
  object); per-field calls are forbidden.

## 7. Done checklist

* [ ] New/changed TOML examples pass `evaluate` with zero errors.
* [ ] New setting/profile/name data has tests in `tests/forge/`.
* [ ] `pytest tests/forge/` green; full `pytest tests/` green.
* [ ] `skill-<npc-type>.md` files render and unknown actions surface.
* [ ] No key material in logs, prompts, bodies, or committed files.
* [ ] `skills/npc-generation-evaluation/SKILL.md` passes with zero errors.
