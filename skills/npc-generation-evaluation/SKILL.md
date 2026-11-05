---
name: npc-generation-evaluation
description: Grade NPC contracts and generated NPCs against the clarity, advice, liveness, and safety rubrics; any error fails back to reiteration.
---

# NPC Generation Evaluation

Grade TOML contracts built under
`skills/npc-generation-contract/SKILL.md` and the NPCs generated from
them. Run every section in order.

**Reiteration rule: any ERROR fails the evaluation.** Fix the TOMLs or
the generator, re-run the full suite, and re-evaluate from section 1.
Warnings do not fail alone, but every warning must be listed in the
report, and more than three warnings fail the evaluation as one error.

## 1. Rubric A -- the clarity gate (errors)

Run `forge.rubric.evaluate(game, quest)` (100 points: schema 25,
coverage 25, references 20, consistency 15, clarity 15).

* E-CLARITY-1: any rubric error (silence on a field, dangling
  location/language/type/profile, `location` open, wandering without
  range, vague brief). **PASS needs zero errors and >= 80.**
* E-CLARITY-2: the generator was run (or patched to run) despite a
  failing gate instead of raising `UnclearContract`.
* W-CLARITY-1 (warning): score 80..89 -- passing but thin; name the
  weakest category in the report.

## 2. Setting fidelity (errors)

* E-SET-1: a 17th personality profile, or a title/name that clashes
  with the setting (sci-fi name on a medieval NPC).
* E-SET-2: new setting/profile/name data without its test in
  `tests/forge/test_profiles.py` / `test_names.py`.
* E-SET-3: a `languages` value outside the game's list, or an empty
  list where the contract demands one.

## 3. Outputs and provenance (errors)

* E-OUT-1: an NPC directory missing `story.md`, `skills.md`,
  `short-memory.json`, `long-memory.json`, or `awareness.md`, or
  written without a passing `NPCSpec.validate`.
* E-OUT-2: `short-memory.json` over cap 20 or newest-first;
  `awareness.md` not deepest-first or leaking a locked hidden detail.
* E-OUT-3: a field whose provenance is not exactly one of
  `fixed` / `template` / `llm`, or a template fill that is not
  byte-identical across runs with the same seed.
* E-OUT-4: a `skill-<npc-type>.md` with an unreported unknown action,
  or instance data losing to the type file on conflict.
* W-OUT-1 (warning): re-run regenerates an unchanged NPC (manifest
  fingerprint broken).

## 4. Rubric B -- model, latency, cost advice (errors)

Run `forge.advisor.advise` for every `(scenario, npc-type)`.

* E-ADV-1: a missing record, a tier outside
  `swift` / `balanced` / `deep`, or stated prices (examples only).
* E-ADV-2: `call_timeout` / `max_attempts` incompatible with the
  quest's `latency_budget_ms` with no warning attached.
* E-ADV-3: no warning when the budget or cost tier cannot host the
  demanded quality.

## 5. Living behavior (errors, for played NPCs)

Generalized from the reference game: generated NPCs must demonstrably
listen, answer, initiate, and remember -- not merely speak when poked.

* E-LIVE-1: overheard in-earshot speech does not reach the hearer's
  short-term memory (no listening trail).
* E-LIVE-2: an NPC addressed by name (or directly messaged) does not
  answer within its latency budget.
* E-LIVE-3: no motive-driven initiation exists (nobody ever speaks
  first), or motives fire without state (greetings with no arrival).
* E-LIVE-4: `history` / `acquaintances` / `export_memory` / `absorb`
  do not round-trip a session back into the artifacts (memories die
  with the process).
* W-LIVE-1 (warning): prompts carry unbounded lore instead of going
  through `prompt_context(spec, budget_chars)`.

## 6. Key safety (errors)

* E-KEY-1: key material in logs, prompts, bodies, committed files, or
  error text; a non-header wire path; any acquisition path outside
  env -> `0600` file -> `getpass` without a contract update + tests.
* E-KEY-2: the game plays scripted fallback lines when no LLM is
  configured instead of refusing to boot (or clearly labeling a
  test stand-in).

## 7. Test files (errors)

* E-TEST-1: `pytest tests/forge/` not green, or the full
  `pytest tests/` suite not green with the addition.
* E-TEST-2: new TOML examples without a clarity-gate test pinning
  zero errors.

## 8. Verdict format

Report one line per check (`pass` / `ERROR <id>` / `warn <id>`), then:

`generation-eval: PASS | FAIL (<n> errors, <m> warnings)`

On FAIL, the builder fixes every error, re-runs the suite, and this
evaluation starts over at section 1. A PASS with warnings names each
warning and its accepted reason.
