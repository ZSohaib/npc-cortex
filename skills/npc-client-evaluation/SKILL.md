---
name: npc-client-evaluation
description: Grade a new npc-cortex engine adapter or native client against the conformance rubric; any error fails it back to reiteration.
---

# npc-cortex Client Evaluation

Grade one engine integration built under
`skills/npc-cortex-engine-adapter/SKILL.md`. Run every section in order
against the submitted code and its tests.

**Reiteration rule: any ERROR fails the evaluation.** Fix the artifact,
re-run the full suite, and re-evaluate from section 1. Warnings do not
fail alone, but every warning must be listed in the report, and more
than three warnings fail the evaluation as one error.

## 1. Integration kind (errors)

* E-KIND-1: wrong kind for the engine (Python-capable engine shipped
  as a network client, or vice versa) without a written rationale.
* E-KIND-2: a core module (`runtime.py`, `models.py`, `geometry.py`,
  `registry.py`, `gateway.py`, `audit.py`, `providers.py`) modified to
  fit the engine.
* E-KIND-3: the engine (or its SDK) imported at module top level, so
  the adapter/client cannot import or test without it installed.

## 2. Frame discipline (errors)

* E-FRAME-1: pump count != frame count over a scripted N-step run.
* E-FRAME-2: blocking I/O (HTTP, sleep, join) reachable from the
  frame/tick callback path. Blocking work must live on a worker
  thread; when a poll is still in flight, the frame skips, never
  queues.
* E-FRAME-3: any game-state effect (provider/handler/gateway/audit
  call, `world_state` write) issued from the adapter directly instead
  of through `pump()` on the calling thread.
* E-FRAME-4: after `close()`, the frame path raises, or
  `cancel()`/`observations()`/`memory()` stop working.

## 3. Wire conformance (errors, native clients)

* E-WIRE-1: a `RemoteBridge` method missing, renamed, or with
  different wire field names (`health`, `submit`, `pump`, `engage`,
  `cancel`, `observations`, `memory`, `audit`, `delivered`,
  `actions`, `register_action`, `sync`, `close`).
* E-WIRE-2: `409` and `429` not mapped to distinct `Closed` /
  `Overloaded` errors.
* E-WIRE-3: per-frame flow out of order (`sync` -> `submit` ->
  `pump` -> cursor polls) or cursors (`since` / `next_since`)
  dropped between polls.
* E-WIRE-4: observations missing the exact keys `handle`,
  `actor_id`, `action`, `phase`.

## 4. Mapping (errors)

* E-MAP-1: mapping is not the identity on components, or a new
  position shape was invented.
* E-MAP-2: no round-trip test (engine vector -> npc position ->
  engine vector), or it fails.
* W-MAP-1 (warning): non-obvious unit choices (centimetres, y-up
  notes) undocumented next to the mapping helper.

## 5. Dialogue integrity (errors)

* E-VOICE-1: any scripted dialogue bank, template line list, or
  canned fallback speech ships in the client. All speech must come
  from the bridge's provider; without a configured LLM the game must
  refuse to boot or clearly label a test stand-in.
* W-VOICE-1 (warning): provider errors surface as silence with no
  surfaced error message or audit trail.

## 6. Test files (errors)

* E-TEST-1: no dedicated per-engine test file (folded into another
  engine's file, or missing).
* E-TEST-2: native client without the Python protocol-conformance
  file against a live `BridgeServer`.
* E-TEST-3: any per-engine test failing, or the full `pytest tests/`
  suite not green with the addition.
* E-TEST-4: duck-typed engine fakes missing where the engine is
  absent, so tests cannot run in CI.

## 7. Documentation (warnings)

* W-DOC-1: `docs/ADAPTERS.md` row missing or pointing at wrong paths.
* W-DOC-2: no client README with flow, coordinates, and check commands.

## 8. Verdict format

Report one line per check (`pass` / `ERROR <id>` / `warn <id>`), then:

`client-eval: PASS | FAIL (<n> errors, <m> warnings)`

On FAIL, the builder fixes every error, re-runs the suite, and this
evaluation starts over at section 1. A PASS with warnings names each
warning and its accepted reason.
