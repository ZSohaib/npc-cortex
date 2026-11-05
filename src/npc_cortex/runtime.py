"""Engine-agnostic runtime (spec sections 3.1-3.10, 3.12-3.13).

This is the original npc_cortex behaviour with the Panda3D frame-loop hook
factored out into :mod:`npc_cortex.adapters`. The only semantic change is
that perception uses :mod:`npc_cortex.geometry`, so 3D positions work;
2D behaviour is identical.
"""

from __future__ import annotations

import json
import random
import threading
import time
from typing import Callable  # noqa: F401  (re-exported for handler authors)

from .geometry import distance  # noqa: F401  (shared perception math)
from .geometry import perceives
from .models import NPC, Player
from .places import WorldMap

__all__ = ["Runtime"]

_TOP_KEYS = {"speech", "emotion", "actions", "memory"}
_ACTION_KEYS = {"name", "parameters"}
_PLAYER_MEMORY_CAP = 20
_NPC_MEMORY_CAP = 5
_TERMINAL = ("completed", "cancelled")
_ACQUAINTANCE_CAP = 64  # distinct actors tracked per NPC (LRU by last seen)


def _disposition(stats) -> str:
    """Warm/wary/neutral from completed vs cancelled outcomes."""
    total = stats["interactions"]
    if total < 2:
        return "neutral"
    if stats["completed"] / total >= 0.6:
        return "warm"
    if stats["cancelled"] / total >= 0.6:
        return "wary"
    return "neutral"


def _validate(raw) -> "dict | None":
    """Structural validation only; the registry is never consulted here."""
    if not isinstance(raw, str):
        return None
    try:
        answer = json.loads(raw)
    except Exception:
        return None
    if not isinstance(answer, dict) or set(answer) != _TOP_KEYS:
        return None
    for key in ("speech", "emotion"):
        value = answer[key]
        if value is not None and not isinstance(value, str):
            return None
    actions = answer["actions"]
    if not isinstance(actions, list):
        return None
    for action in actions:
        if not isinstance(action, dict) or set(action) != _ACTION_KEYS:
            return None
        if not isinstance(action["name"], str):
            return None
        if not isinstance(action["parameters"], dict):
            return None
    memory = answer["memory"]
    if not isinstance(memory, list):
        return None
    for item in memory:
        if not isinstance(item, str):
            return None
    return answer


class _Slot:
    """One submitted event, holding its submission-order position."""

    __slots__ = (
        "event", "npc", "epoch", "ready", "result",
        "attempts", "seq", "deadline", "last_error",
    )

    def __init__(self, event, npc, epoch) -> None:
        self.event = event
        self.npc = npc
        self.epoch = epoch
        self.ready = False
        self.result = None          # ("skip"|"answer"|"error"|"timeout", payload)
        self.attempts = 0
        self.seq = 0                # bumped to invalidate an abandoned attempt
        self.deadline = 0.0
        self.last_error = None


class _Engagement:
    """One player engagement and its streamline lifecycle."""

    __slots__ = (
        "handle", "player", "name", "parameters", "handler", "broadcast",
        "duration", "state", "epoch", "started_at", "outcome", "observers",
        "forced",
    )

    def __init__(self, handle, player, name, parameters, epoch) -> None:
        self.handle = handle
        self.player = player
        self.name = name
        self.parameters = parameters
        self.handler = None
        self.broadcast = False
        self.duration = 0.0
        self.state = "void"        # void | queued | live | done
        self.epoch = epoch
        self.started_at = 0.0
        self.outcome = None
        self.observers: list = []
        self.forced = False


class Runtime:
    def __init__(
        self,
        scenario,
        provider,
        registry,
        gateway,
        audit,
        *,
        call_timeout: float = 2.0,
        max_attempts: int = 3,
        capacity: int = 1024,
    ) -> None:
        self.scenario = scenario
        self.provider = provider
        self.registry = registry
        self.gateway = gateway
        self.audit = audit
        self.call_timeout = float(call_timeout)
        self.max_attempts = int(max_attempts)
        self.capacity = int(capacity)

        self._pending: list = []          # event slots, submission order
        self._npc_wait: dict = {}         # npc id -> slots waiting for the npc
        self._running: dict = {}          # npc id -> slot with an outstanding attempt
        self._engagements: dict = {}      # handle -> _Engagement
        self._queue: list = []            # handles awaiting streamline entry
        self._live: list = []             # handles in streamline, entry order
        self._observations: dict = {}     # character id -> list[dict]
        self._memory: dict = {}           # npc id -> {"players": [], "npcs": []}
        self._acquaintances: dict = {}    # npc id -> actor id -> stats
        self._handles = 0
        self._epoch = 0                   # bumped once per pump(), for 3.3
        self._closed = False
        self._random = random.Random()
        # Reentrant: a handler running under pump() may re-enter the public API.
        self._cv = threading.Condition(threading.RLock())
        self._driver = threading.Thread(target=self._drive, daemon=True)
        self._driver.start()

    # -- scenario lookup --------------------------------------------------

    def _find_npc(self, npc_id):
        for npc in self.scenario.npcs:
            if npc.id == npc_id:
                return npc
        return None

    def _find_player(self, player_id):
        for player in self.scenario.players:
            if player.id == player_id:
                return player
        return None

    # -- perception (3.6) -------------------------------------------------

    def _perceives(self, observer, actor, broadcast=False) -> bool:
        return perceives(observer, actor, broadcast)

    def _observers(self, actor, broadcast) -> list:
        found = []
        for observer in list(self.scenario.players) + list(self.scenario.npcs):
            if self._perceives(observer, actor, broadcast):
                found.append(observer)
        return found

    # -- observation records (3.8) and memory (3.9) -----------------------

    def _observe(self, observers, handle, actor_id, action, phase, bucket) -> None:
        for observer in observers:
            with self._cv:
                self._observations.setdefault(observer.id, []).append(
                    {
                        "handle": handle,
                        "actor_id": actor_id,
                        "action": action,
                        "phase": phase,
                    }
                )
                if isinstance(observer, NPC) and phase in _TERMINAL:
                    self._remember(observer.id, actor_id, action, phase, bucket)
                    self._acquaint(observer.id, actor_id, action, phase)

    def _remember(self, npc_id, actor_id, action, outcome, bucket) -> None:
        slot = self._memory.setdefault(npc_id, {"players": [], "npcs": []})
        entries = slot[bucket]
        entries.append({"actor_id": actor_id, "action": action, "outcome": outcome})
        cap = _PLAYER_MEMORY_CAP if bucket == "players" else _NPC_MEMORY_CAP
        while len(entries) > cap:
            entries.pop(0)

    def _acquaint(self, npc_id, actor_id, action, outcome) -> None:
        """Fold one observed outcome into the per-actor relationship.

        Caller holds the lock (called from ``_observe``). NPCs never
        record their own actions: observers never receive their own
        records in the first place.
        """
        table = self._acquaintances.setdefault(npc_id, {})
        stats = table.get(actor_id)
        if stats is None:
            stats = {"interactions": 0, "completed": 0, "cancelled": 0,
                     "actions": {}, "first_seen": self._epoch,
                     "last_seen": self._epoch}
            table[actor_id] = stats
            # Newest last_seen is now, so ties evict the oldest resident.
            while len(table) > _ACQUAINTANCE_CAP:
                oldest = min(table, key=lambda k: table[k]["last_seen"])
                del table[oldest]
        stats["interactions"] += 1
        stats["completed" if outcome == "completed" else "cancelled"] += 1
        stats["actions"][action] = stats["actions"].get(action, 0) + 1
        stats["last_seen"] = self._epoch

    def observations(self, character_id: str) -> list:
        with self._cv:
            return [dict(record) for record in self._observations.get(character_id, ())]

    def surroundings(self, npc_id: str, radius: float = 20.0) -> list:
        """Places near an NPC, nearest first: ``id``, ``kind``,
        ``distance``, ``description``, ``public``.

        A live spatial sense -- what is around right now. Existence and
        looks are observable by anyone nearby; owners, interiors, and
        hidden details are *not* included here (see
        ``npc_cortex.places.knowledge`` + forge familiarity for those).
        Returns ``[]`` for an unknown NPC; works after ``close()`` like
        the other read APIs.
        """
        with self._cv:
            npc = self._find_npc(npc_id)
            if npc is None:
                return []
            nearby = WorldMap(self.scenario.places or []).nearby(
                npc.position, radius)
            return [{"id": place.id, "kind": place.kind, "distance": dist,
                     "description": place.description,
                     "public": bool(place.public)}
                    for place, dist in nearby]

    def memory(self, npc_id: str) -> dict:
        with self._cv:
            if self._find_npc(npc_id) is None:
                return {"players": [], "npcs": []}
            slot = self._memory.get(npc_id)
            if slot is None:
                return {"players": [], "npcs": []}
            return {
                "players": [dict(e) for e in slot["players"]],
                "npcs": [dict(e) for e in slot["npcs"]],
            }

    def history(self, npc_id: str, actor_id=None, limit=None) -> list:
        """Records received by ``npc_id``, append order (oldest first).

        The specific shared history with one actor (``actor_id`` set) or
        with everyone. ``limit`` keeps the most recent records -- the
        short-term window. ``[]`` for an unknown NPC; works after
        ``close()`` like the other read APIs.
        """
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be an int >= 0")
        with self._cv:
            records = self._observations.get(npc_id, ())
            if actor_id is not None:
                records = [r for r in records if r["actor_id"] == actor_id]
            records = [dict(record) for record in records]
            if limit is not None:
                records = records[max(0, len(records) - limit):]
            return records

    def acquaintances(self, npc_id: str) -> dict:
        """Long-term knowledge ``npc_id`` developed about each actor.

        ``{actor_id: {interactions, completed, cancelled, actions,
        first_seen, last_seen, disposition}}``, where the ``*_seen``
        stamps are pump epochs and ``disposition`` is ``warm``,
        ``wary``, or ``neutral``. ``{}`` for an unknown NPC; works
        after ``close()``.
        """
        with self._cv:
            if self._find_npc(npc_id) is None:
                return {}
            table = self._acquaintances.get(npc_id, {})
            return {actor: {"interactions": stats["interactions"],
                            "completed": stats["completed"],
                            "cancelled": stats["cancelled"],
                            "actions": dict(stats["actions"]),
                            "first_seen": stats["first_seen"],
                            "last_seen": stats["last_seen"],
                            "disposition": _disposition(stats)}
                    for actor, stats in table.items()}

    def export_memory(self, npc_id: str) -> dict:
        """Lived memory in forge artifact shapes.

        ``{"short_memory": [...], "long_memory": [...]}`` -- the recent
        records plus one distilled fact per acquaintance. Feed it to
        ``NPCSpec.absorb`` to persist a session back into artifacts.
        Empty lists for an unknown NPC; works after ``close()``.
        """
        with self._cv:
            if self._find_npc(npc_id) is None:
                return {"short_memory": [], "long_memory": []}
            records = self._observations.get(npc_id, ())
            short = [{"text": "%s %s (%s)" % (r["actor_id"], r["action"],
                                              r["phase"]),
                      "tags": [r["phase"], r["action"]]}
                     for r in records[-20:]]
            table = self._acquaintances.get(npc_id, {})
            long = []
            for actor in sorted(table):
                stats = table[actor]
                mood = _disposition(stats)
                long.append({
                    "fact": "Knows %s: %d interaction(s), %d completed, "
                            "%d cancelled (%s)." % (
                                actor, stats["interactions"],
                                stats["completed"], stats["cancelled"], mood),
                    "tags": ["acquaintance", mood]})
            return {"short_memory": short, "long_memory": long}

    # -- submission (3.1, 3.2, 3.4) ---------------------------------------

    def submit(self, event) -> None:
        with self._cv:
            if self._closed:
                raise Closed("runtime is closed")
            if len(self._pending) >= self.capacity:
                raise Overloaded("runtime holds %d unresolved events" % self.capacity)
            npc = self._find_npc(event.npc_id)
            slot = _Slot(event, npc, self._epoch)
            self._pending.append(slot)
            # An unknown NPC and the zero gate are both decided here, at
            # submission time, and neither ever reaches the provider.
            if npc is None or float(npc.implication) == 0.0:
                slot.result = ("skip", None)
                slot.ready = True
                return
            self._npc_wait.setdefault(event.npc_id, []).append(slot)
            self._dispatch(event.npc_id)

    def _prompt(self, slot) -> str:
        """Carries the npc id and the event text through verbatim (3.2)."""
        event = slot.event
        return "\n".join(
            [
                "npc=" + slot.npc.id,
                "kind=" + str(event.kind),
                "speaker=" + ("" if event.speaker_id is None else event.speaker_id),
                "text=" + ("" if event.text is None else event.text),
                "memory=" + json.dumps(self.memory(event.npc_id)),
            ]
        )

    def _dispatch(self, npc_id) -> None:
        """Start the next attempt for an idle npc. Caller holds the lock."""
        if self._closed or npc_id in self._running:
            return
        queue = self._npc_wait.get(npc_id)
        if not queue:
            return
        self._start_attempt(queue.pop(0))

    def _start_attempt(self, slot) -> None:
        """Caller holds the lock."""
        slot.attempts += 1
        slot.seq += 1
        slot.deadline = time.monotonic() + self.call_timeout
        self._running[slot.event.npc_id] = slot
        threading.Thread(
            target=self._worker,
            args=(slot, slot.seq, self._prompt(slot)),
            daemon=True,
        ).start()
        self._cv.notify_all()

    def _worker(self, slot, seq, prompt) -> None:
        """Background work: records a raw result only, mutates no game state."""
        try:
            raw = self.provider.complete(prompt)
            error = None
        except BaseException as exc:      # contained; surfaced at resolve time
            raw, error = None, exc
        with self._cv:
            if self._closed or slot.ready or slot.seq != seq:
                return                    # abandoned: no effect on anything
            self._finish_attempt(slot, raw, error, timed_out=False)
            self._cv.notify_all()

    def _finish_attempt(self, slot, raw, error, timed_out) -> None:
        """Caller holds the lock."""
        npc_id = slot.event.npc_id
        if error is None and not timed_out:
            slot.result = ("answer", raw)
        else:
            slot.last_error = error
            if slot.attempts < self.max_attempts and not self._closed:
                self._start_attempt(slot)     # keeps this npc's single slot
                return
            slot.result = ("timeout", None) if timed_out else ("error", error)
        slot.ready = True
        if self._running.get(npc_id) is slot:
            del self._running[npc_id]
        self._dispatch(npc_id)

    def _drive(self) -> None:
        """Abandons overdue attempts without pump() being called (3.2)."""
        with self._cv:
            while not self._closed:
                now = time.monotonic()
                for slot in [s for s in self._running.values() if s.deadline <= now]:
                    if self._running.get(slot.event.npc_id) is not slot:
                        continue
                    self._finish_attempt(slot, None, None, timed_out=True)
                if self._closed:
                    return
                deadlines = [s.deadline for s in self._running.values()]
                wait = None
                if deadlines:
                    wait = max(0.0, min(deadlines) - time.monotonic())
                self._cv.wait(wait)

    # -- engagements (3.7) ------------------------------------------------

    def engage(self, player_id: str, name: str, parameters: dict, duration: float) -> str:
        with self._cv:
            if self._closed:
                raise Closed("runtime is closed")
            self._handles += 1
            handle = "engagement-%d" % self._handles
            epoch = self._epoch
        player = self._find_player(player_id)
        entry = self.registry.lookup(name)
        try:
            params = dict(parameters)
        except Exception:
            params = {}
            entry = None
        engagement = _Engagement(handle, player, name, params, epoch)
        eligible = player is not None and entry is not None
        if eligible:
            spec, _min_implication, handler, broadcast = entry
            eligible = set(params) == set(spec)
        if eligible:
            eligible = all(isinstance(params[key], spec[key]) for key in spec)
        if eligible:
            try:
                eligible = float(duration) > 0.0
            except Exception:
                eligible = False
        if eligible:
            engagement.handler = handler
            engagement.broadcast = broadcast
            engagement.duration = float(duration)
            engagement.state = "queued"
        with self._cv:
            self._engagements[handle] = engagement
            if eligible:
                self._queue.append(handle)
        return handle

    def cancel(self, handle: str) -> None:
        with self._cv:
            engagement = self._engagements.get(handle)
            if engagement is None:
                return                      # never issued by engage(): inert
            if engagement.state == "queued":
                engagement.state = "void"   # discarded before streamline
                try:
                    self._queue.remove(handle)
                except ValueError:
                    pass
            elif engagement.state == "live":
                engagement.forced = True
            # "void" and "done" are inert.

    def _call_handler(self, handler, npc, parameters) -> None:
        """A raising handler is contained (3.5, 3.7)."""
        try:
            handler(self.scenario, npc, parameters)
        except BaseException:
            pass

    def _advance_engagements(self, epoch) -> None:
        now = time.monotonic()

        with self._cv:
            ready = [h for h in self._queue if self._engagements[h].epoch < epoch]
            self._queue = [h for h in self._queue if h not in set(ready)]
            entering = [self._engagements[h] for h in ready]

        for engagement in entering:
            with self._cv:
                if engagement.state != "queued":
                    continue            # cancelled before it could enter
                engagement.state = "live"
                engagement.started_at = now
                engagement.outcome = (
                    "completed" if self._random.random() < 0.5 else "cancelled"
                )
                engagement.observers = self._observers(
                    engagement.player, engagement.broadcast
                )
                self._live.append(engagement.handle)
            self._observe(
                engagement.observers,
                engagement.handle,
                engagement.player.id,
                engagement.name,
                "started",
                "players",
            )
            self._audit_engage("engage_started", engagement.name)

        with self._cv:
            live = [self._engagements[h] for h in self._live]

        finished = []
        for engagement in live:
            if engagement.state != "live":
                continue
            if engagement.forced:
                outcome = "cancelled"
            else:
                deadline = (
                    engagement.duration
                    if engagement.outcome == "completed"
                    else engagement.duration / 2.0
                )
                if now - engagement.started_at < deadline:
                    continue
                outcome = engagement.outcome
            engagement.state = "done"
            engagement.outcome = outcome
            finished.append(engagement)
            if outcome == "completed":
                self._call_handler(
                    engagement.handler, None, dict(engagement.parameters)
                )
            self._observe(
                engagement.observers,
                engagement.handle,
                engagement.player.id,
                engagement.name,
                outcome,
                "players",
            )
            self._audit_engage("engage_" + outcome, engagement.name)

        if finished:
            done = {engagement.handle for engagement in finished}
            with self._cv:
                self._live = [h for h in self._live if h not in done]

    # -- pumping (3.1, 3.3) -----------------------------------------------

    def pump(self) -> int:
        with self._cv:
            if self._closed:
                raise Closed("runtime is closed")
            self._epoch += 1
            epoch = self._epoch
        self._advance_engagements(epoch)
        resolved = 0
        while True:
            with self._cv:
                if self._closed or not self._pending:
                    break
                slot = self._pending[0]
                # Not ready yet, or created by a handler under this same
                # pump(): either way the queue stops here.
                if not slot.ready or slot.epoch >= epoch:
                    break
                self._pending.pop(0)
            self._resolve(slot)
            resolved += 1
        return resolved

    def _resolve(self, slot) -> None:
        event = slot.event
        kind, payload = slot.result
        if kind == "skip":
            return
        if kind == "error":
            self._audit(event, "provider_error", type(payload).__name__)
            return
        if kind == "timeout":
            self._audit(event, "provider_timeout", "")
            return
        answer = _validate(payload)
        if answer is None:
            self._audit(event, "invalid_answer", "")
            return
        npc = slot.npc
        for action in answer["actions"]:
            self._act(event, npc, action)
        speech = answer["speech"]
        if speech is not None:
            for player in self.scenario.players:
                if self._perceives(player, npc):
                    self.gateway.deliver(player.id, speech)
        # The memory strings carried by the answer are validated and discarded.

    def _act(self, event, npc, action) -> None:
        name = action["name"]
        parameters = action["parameters"]
        entry = self.registry.lookup(name)
        accepted = entry is not None
        if accepted:
            spec, min_implication, handler, broadcast = entry
            accepted = set(parameters) == set(spec)
        if accepted:
            accepted = all(isinstance(parameters[k], spec[k]) for k in spec)
        if accepted:
            accepted = float(npc.implication) >= min_implication
        if not accepted:
            self._audit(event, "action_rejected", name)
            return
        self._audit(event, "action_accepted", name)
        observers = self._observers(npc, broadcast)
        self._call_handler(handler, npc, parameters)
        self._observe(observers, "", npc.id, name, "completed", "npcs")

    # -- audit (3.10) -----------------------------------------------------

    def _audit(self, event, kind, detail) -> None:
        self.audit.records.append(
            {
                "kind": kind,
                "npc_id": event.npc_id,
                "event_kind": event.kind,
                "detail": detail,
            }
        )

    def _audit_engage(self, kind, detail) -> None:
        self.audit.records.append(
            {
                "kind": kind,
                "npc_id": "",
                "event_kind": "engage",
                "detail": detail,
            }
        )

    # -- shutdown (3.12) --------------------------------------------------

    def close(self) -> None:
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._pending = []        # unresolved events never resolve
            self._npc_wait.clear()
            self._running.clear()
            self._queue = []
            self._live = []
            self._cv.notify_all()
        # Outstanding provider calls are never joined: one of them may be
        # parked inside a slow provider, and close() has a 1.0s ceiling.
        self._driver.join(timeout=0.5)


# Imported late: models must not depend on the runtime.
from .models import Closed, Overloaded  # noqa: E402  (re-exported names)
