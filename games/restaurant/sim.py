"""Maison Cinq simulation: demand-supply restaurant on Panda3D tasks.

Panda3D drives the loop (headless ``TaskManager``): npc-cortex pumps once
per step, and game tasks advance customers, kitchen, and chatter. Works
with real Panda3D or a built-in shim (tests without Panda3D installed).

Demand: customer parties arrive over time. Supply: 6 tables, a 2-slot
kitchen, roaming waiters. Satisfaction, revenue, and rating fall out of
wait times; the player (any role) or passive watching just changes who
gets to act.
"""

from __future__ import annotations

import random
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

try:
    from direct.task.Task import Task, TaskManager
    CONT, DONE = Task.cont, Task.done
except ImportError:  # shim path (tested where Panda3D is absent)
    Task = None
    TaskManager = None
    CONT, DONE = "cont", "done"

import npc_cortex as m
from npc_cortex.forge import NPCGenerator, load_game, load_quest
from npc_cortex.geometry import distance

HERE = Path(__file__).resolve().parent
TICK_HZ = 10

MENU = [
    {"dish": "Truffle Risotto", "price": 45, "prep": 150},
    {"dish": "Duck Confit", "price": 38, "prep": 120},
    {"dish": "Bouillabaisse", "price": 32, "prep": 100},
    {"dish": "Ratatouille", "price": 22, "prep": 80},
]

TABLES = [
    {"id": "t1", "seats": 2}, {"id": "t2", "seats": 2},
    {"id": "t3", "seats": 4}, {"id": "t4", "seats": 4},
    {"id": "t5", "seats": 2}, {"id": "t6", "seats": 4},
]

STAFF_HOME = {"celeste": "dining_hall", "theo": "entrance", "nina": "dining_hall",
              "omar": "dining_hall", "auguste": "kitchen", "leo": "kitchen",
              "priya": "bar"}

ROLE_ACTIONS = {
    "customer": ["order_dish", "pay_bill", "order_drink"],
    "waiter": ["take_order", "serve_dish", "serve_next"],
    "chef": ["cook_dish", "cook_next"],
    "manager": ["comp_dish", "rush_order", "seat_next", "greet"],
}

UTILITIES = [
    {"id": "bar", "label": "Bar", "x": 32.0, "y": 4.0, "radius": 5.0},
    {"id": "pass", "label": "Kitchen pass", "x": 33.5, "y": 17.5, "radius": 5.0},
    {"id": "host_stand", "label": "Host stand", "x": 2.0, "y": 12.0, "radius": 5.0},
]

ROLE_SPOT = {"customer": "bar", "waiter": "dining_hall",
             "chef": "kitchen", "manager": "dining_hall"}

# Pacing: the sim ticks at 10Hz; every service step gets a humane window.
SPAWN_EVERY = 150      # a new party about every 15s
CHATTER_EVERY = 150    # one ambient line about every 15s (+/- jitter)
QUEUE_PATIENCE = 900   # 90s in line before a party storms out
SEAT_PATIENCE = 1500   # 2.5min ignored at table before storming out
BROWSE_TICKS = 200     # 20s with the menu before the waiter comes
DISCUSS_GAP = 45       # ~4.5s between ordering-discussion turns
SERVE_DELAY = 80       # 8s a plated dish waits at the pass
EAT_TICKS = 320        # ~32s to enjoy the meal
PAY_TICKS = 80         # 8s to settle the bill
GREET_BOOST = 200
WALK_TOL = 1.5
INITIATIVE_EVERY = 120   # someone finds a reason to speak ~every 12s
ADDRESS_COOLDOWN = 150   # per-NPC gap between name-mention replies
PLAYER_IDLE_TICKS = 300  # silence before an NPC may address the player
LEARN_EVERY = 600        # absorb lived memory into specs, ~every minute
CHAT_PIN_WINDOW = 900    # a chatted-with guest stays while talked to
LINGER_SPOTS = [(30.0, 5.5), (31.5, 5.5), (33.0, 5.5), (34.5, 5.5)]

# Party kinds: (kind, min_size, max_size, weight).
PARTY_KINDS = (("solo", 1, 1, 0.30), ("couple", 2, 2, 0.30),
               ("friends", 2, 3, 0.20), ("family", 3, 4, 0.20))

SURNAMES = ["Marchand", "Alvarez", "Petrova", "Haddad", "Blanc",
            "Fischer", "Nair", "Rossi", "Kowalski", "Tanaka", "Okafor",
            "Lindqvist", "Papadopoulos", "Silva", "Moreau", "Khan"]

# Seat offsets around a table center (up to 4 guests).
TABLE_SPOTS = [(-1.4, -1.2), (1.4, -1.2), (-1.4, 1.2), (1.4, 1.2)]
QUEUE_SPOT = (3.0, 10.0)
EXIT_SPOT = (2.0, 12.0)


class ShimTaskManager:
    """Duck-typed TaskManager for installs without Panda3D."""

    def __init__(self) -> None:
        self._tasks = []

    def add(self, fn, name):
        task = {"fn": fn, "name": name}
        self._tasks.append(task)
        return task

    def step(self):
        for task in list(self._tasks):
            if task["fn"](task) == DONE:
                self._tasks.remove(task)


def make_task_manager():
    """Real Panda3D TaskManager when importable, else the shim."""
    if TaskManager is not None:
        return TaskManager()
    return ShimTaskManager()


class Sim:
    def __init__(self, provider, seed: int = 5, out_dir=None) -> None:
        self.rng = random.Random(seed)
        self.tick_count = 0
        game = load_game(HERE / "forge" / "game-description.toml")
        quest = load_quest(HERE / "forge" / "game-quest-1.toml")
        out = Path(out_dir) if out_dir else HERE / "out"
        self._out_dir = out
        self._customer_seq = 8
        self._spawn_in = 50
        self._spec_home = {}  # npc_id -> quest dir for artifacts
        report = NPCGenerator(game, [quest], seed=seed).run(out, refresh=True)
        self.game, self.specs = game, {s.id: s for s in report.npcs}
        for sid in self.specs:
            self._spec_home[sid] = quest.id
        self.coords = {name: loc["coords"] for name, loc in game.locations.items()}
        for pid, place in game.places.items():
            self.coords[pid] = place.coords

        self.player = m.Player(id="you", role="customer",
                               position=self.coords["bar"], horizon=1000.0,
                               online=True)
        npcs = [s.to_runtime_npc(game, horizon=12.0, implication=0.7)
                for s in report.npcs]
        self.scenario = m.Scenario(players=[self.player], npcs=npcs,
                                   world_state={},
                                   places=list(game.places.values()))
        self.registry = m.ActionRegistry()
        self.gateway = m.Gateway()
        self.audit = m.AuditLog()
        # Hosted-LLM generous deadline: lines arrive in seconds, and a
        # dropped line is a missed beat on the floor.
        self.runtime = m.Runtime(self.scenario, provider, self.registry,
                                 self.gateway, self.audit, call_timeout=15.0)
        self._register_actions()
        # Speaker-attributed speech (gateway.delivered only names the
        # recipient). Appended from provider threads; guarded by lock.
        self._spoken_lock = threading.Lock()
        self.spoken = []
        self.transcript = []  # multilogue: tick, by, text, heard_by
        self._stage_ctx = {}  # npc_id -> staged-line slots (async-safe)
        # Listening: what each NPC overheard lately (short-term, live).
        self._heard = {}      # npc_id -> deque[{by, text, tick}]
        self._pending_hear = []  # transcript entries awaiting hearers
        self._pending_lines = []  # [(tick, npc, stage, table, dish, to_you)]
        self._address_cd = {}    # npc_id -> tick of last mention-reply
        self._initiative_in = 40
        self._last_player_talk = 0
        self._player_idle_cd = 0
        self._learn_in = LEARN_EVERY
        if hasattr(provider, "on_speech"):
            provider.on_speech = self._record_speech
        if hasattr(provider, "on_reply"):
            provider.on_reply = self._record_reply
        provider.persona_fn = self._persona
        provider.recent_fn = self._recent_texts
        provider.known_fn = self._player_knows

        # entity visuals + flow state
        self.entities = {}
        for spec in report.npcs:
            x, y = self._at(spec.location)
            staff = spec.npc_type != "customer"
            self.entities[spec.id] = {
                "id": spec.id, "name": spec.name,
                "kind": "staff" if staff else "customer",
                "role": spec.npc_type, "x": float(x), "y": float(y),
                "tx": float(x), "ty": float(y),
                "speed": 6.5 if staff else 4.5,
                "state": "idle", "table": None, "party": None,
                "task": None,
            }
        self.entities["you"] = {
            "id": "you", "name": "You", "kind": "player", "role": "customer",
            "x": 32.0, "y": 4.0, "tx": 32.0, "ty": 4.0, "speed": 8.0,
            "state": "idle", "table": None, "party": None,
        }
        self.tables = {t["id"]: {"id": t["id"], "seats": t["seats"],
                                 "guest": None, "guests": [],
                                 "party": None} for t in TABLES}
        self.orders = {}       # oid -> order dict
        self._oids = 0
        # Parties: the flow unit. Per-cid `flow` entries mirror party state
        # for the UI and older callers.
        self.parties = {}
        self._party_seq = 0
        self.flow = {}
        guests = [s.id for s in report.npcs if s.npc_type == "customer"]
        for pid, members, kind in (("p1", guests[0:1], "solo"),
                                   ("p2", guests[1:3], "couple"),
                                   ("p3", guests[3:6], "family"),
                                   ("p4", guests[6:8], "couple")):
            self._party_seq += 1
            timer = 20 + 25 * (self._party_seq - 1)
            self.parties[pid] = {
                "id": pid, "kind": kind, "members": list(members),
                "state": "away", "timer": timer, "table": None,
                "waiter": None, "turn": 0, "turn_timer": 0,
                "patience": QUEUE_PATIENCE, "waited": 0,
            }
            for cid in members:
                self.flow[cid] = {"state": "away", "timer": timer,
                                  "table": None, "order": None,
                                  "dish": None, "food": None,
                                  "party": pid}
                self.entities[cid]["party"] = pid
        self._share_surname("p3")
        self.player_tab = {"orders": [], "paid": 0}
        self.stats = {"revenue": 0, "served": 0, "lost": 0,
                      "satisfaction": [], "tick": 0}
        self.events = []  # [{kind, x, y, tick}] canvas feedback flashes
        self.mode = "active"
        self.lang = "english"
        self._chatter_in = 60
        # Player chat threads: npc_id -> {"known", "messages"}; staff are
        # known crew, guests start as strangers. Persisted as chat.json.
        self.chats = {s.id: {"known": s.npc_type != "customer",
                             "messages": []}
                      for s in report.npcs}
        self._load_chats()

    def _record_speech(self, npc_id, speech):
        with self._spoken_lock:
            if (self.transcript and self.transcript[-1]["by"] == npc_id
                    and self.transcript[-1]["text"] == speech):
                return  # safety net: never log the same line twice in a row
            self.spoken.append({"by": npc_id, "text": speech})
            entry = {"tick": self.tick_count, "by": npc_id,
                     "text": speech, "heard_by": None}
            self.transcript.append(entry)
            del self.transcript[:-200]
            self._pending_hear.append(entry)
            del self._pending_hear[:-50]

    def _drain_listening(self):
        """Main-thread hear pass: hearers, overheard memory, addressing."""
        with self._spoken_lock:
            entries = self._pending_hear
            self._pending_hear = []
        if not entries:
            return
        self._fill_hearers_for(entries)
        for entry in entries:
            for hid in entry["heard_by"] or []:
                if hid == "you" or hid not in self.entities:
                    continue
                buf = self._heard.setdefault(hid, deque(maxlen=6))
                buf.append({"by": entry["by"], "text": entry["text"],
                            "tick": entry["tick"]})
        self._address_checks(entries)

    def _address_checks(self, entries):
        """A hearer named by first name answers (cooldown-gated)."""
        for entry in entries:
            low = entry["text"].lower()
            for hid in entry["heard_by"] or []:
                if hid in ("you", entry["by"]) or hid not in self.entities:
                    continue
                first = self.entities[hid]["name"].split(" ")[0].lower()
                if not first or first not in low:
                    continue
                if self.tick_count - self._address_cd.get(hid, -9999) \
                        < ADDRESS_COOLDOWN:
                    continue
                self._address_cd[hid] = self.tick_count
                try:
                    self.runtime.submit(m.Event(
                        kind="direct_message", npc_id=hid,
                        speaker_id=entry["by"],
                        text="[lang:%s] %s" % (self.lang, entry["text"])))
                except (m.Overloaded, m.Closed):
                    pass

    def _record_reply(self, npc_id, speech):
        """An NPC answers the player: transcript + chat thread + learned."""
        self._record_speech(npc_id, speech)
        thread = self.chats.setdefault(npc_id, {"known": False,
                                                "messages": []})
        thread["messages"].append({"by": npc_id, "text": speech,
                                   "tick": self.tick_count})
        del thread["messages"][:-50]
        thread["known"] = True
        self._save_chats()

    # -- provider hooks: persona, room memory, name knowledge -------------

    def _persona(self, npc_id, speaker=None):
        """Full LLM context: skills, persona, history, memories, place."""
        spec = self.specs.get(npc_id)
        entity = self.entities.get(npc_id, {})
        flow = self.flow.get(npc_id, {})
        party = self.parties.get(flow.get("party") or "", {})
        if not party:  # staff: the party on their current task, if any
            task = entity.get("task") or {}
            party = self.parties.get(task.get("pid") or "", {})
        mates = [self.entities.get(m, {}).get("name", "").split(" ")[0]
                 for m in party.get("members", []) if m != npc_id]
        try:
            title = spec.title("modern") if spec else ""
        except Exception:
            title = ""
        dishes = [self.flow.get(m, {}).get("dish") or "chef's special"
                  for m in party.get("members", [])]
        staged = self._stage_ctx.get(npc_id, {})
        table = flow.get("table") or party.get("table") or ""
        name = entity.get("name") or (spec.name if spec else npc_id)
        persona = {
            "name": name, "first": name.split(" ")[0],
            "role": entity.get("role") or "guest",
            "staff": entity.get("kind") == "staff",
            "profile": title, "story": spec.story if spec else "",
            "dish": flow.get("dish") or "chef's special",
            "dishes": staged.get("dishes") or ", ".join("the " + d
                                                       for d in dishes),
            "table": table[1:] if table.startswith("t") else table,
            "other": mates[0] if mates else "my friend",
        }
        if spec is not None:
            persona["skills"] = [
                "%s -- %s" % (s.get("name"), s.get("description", ""))
                for s in (spec.skills or [])[:6]]
            persona["short_memory"] = [
                e.get("text", "") for e in (spec.short_memory or [])[-5:]]
            persona["long_memory"] = [
                (e.get("fact", "") if isinstance(e, dict) else str(e))
                for e in (spec.long_memory or [])[-5:]]
            try:
                persona["aware"] = [
                    "%s (familiarity %d): %s" % (
                        pid, entry.get("familiarity", 0),
                        "; ".join(
                            str(v) for k, v in
                            (entry.get("facts") or {}).items()
                            if k in ("description", "owner", "interior")
                            and v) or "a known place")
                    for pid, entry in spec.known_places()[:2]]
            except Exception:
                persona["aware"] = []
        persona["heard"] = [
            '"%s" -- %s' % (h["text"], h["by"])
            for h in list(self._heard.get(npc_id, ()))[-3:]]
        try:
            persona["near"] = [
                "%s (%s, %.0fu): %s" % (p["id"], p["kind"], p["distance"],
                                        p["description"])
                for p in self.runtime.surroundings(npc_id, 12.0)[:4]]
        except Exception:
            persona["near"] = []
        try:
            me = (entity.get("x", 0.0), entity.get("y", 0.0))
            actors = []
            for eid, other in list(self.entities.items()):
                if eid in (npc_id, "you") or eid not in self.specs:
                    continue
                dist = ((other["x"] - me[0]) ** 2
                        + (other["y"] - me[1]) ** 2) ** 0.5
                if dist <= 12.0:
                    actors.append("%s (%.0fu)" % (other["name"], dist))
            persona["actors"] = actors[:6]
        except Exception:
            persona["actors"] = []
        if speaker:
            try:
                persona["history"] = [
                    "%s %s (%s)" % (r["actor_id"], r["action"], r["phase"])
                    for r in self.runtime.history(npc_id, speaker, 3)]
            except Exception:
                persona["history"] = []
            try:
                rel = self.runtime.acquaintances(npc_id).get(speaker, {})
                persona["relation"] = (
                    "%d interactions, %s" % (rel["interactions"],
                                             rel["disposition"]) if rel else "")
            except Exception:
                persona["relation"] = ""
            if speaker == "you":
                thread = self.chats.get(npc_id, {}).get("messages", [])
                persona["chat"] = [
                    "%s: %s" % ("you" if m["by"] == "you" else name.split(" ")[0],
                                m["text"])
                    for m in thread[-4:]]
            else:
                persona["chat"] = []
        else:
            persona["history"] = []
            persona["relation"] = ""
            persona["chat"] = []
        return persona

    def _recent_texts(self, n):
        with self._spoken_lock:
            return [e["text"] for e in self.transcript[-max(0, n):]]

    def _player_knows(self, npc_id):
        if npc_id == "you":
            return True
        return bool(self.chats.get(npc_id, {}).get("known", False))

    # -- chat threads (persisted record of player discussions) ------------

    def _chat_path(self):
        return self._out_dir / "chat.json"

    def _save_chats(self):
        try:
            import json
            self._out_dir.mkdir(parents=True, exist_ok=True)
            self._chat_path().write_text(json.dumps(self.chats), encoding="utf-8")
        except Exception:
            pass  # the record is a courtesy; the game never depends on it

    def _load_chats(self):
        try:
            import json
            raw = self._chat_path().read_text(encoding="utf-8")
            saved = json.loads(raw)
        except Exception:
            return
        if not isinstance(saved, dict):
            return
        for nid, thread in saved.items():
            if not isinstance(thread, dict):
                continue
            slot = self.chats.setdefault(nid, {"known": False, "messages": []})
            slot["known"] = bool(thread.get("known", slot["known"]))
            messages = thread.get("messages", [])
            if isinstance(messages, list):
                slot["messages"] = [m for m in messages[-50:]
                                    if isinstance(m, dict)]

    def _share_surname(self, pid):
        """Family party: all members share the first member's surname."""
        party = self.parties.get(pid)
        if not party or not party["members"]:
            return
        surname = self.entities[party["members"][0]]["name"].split(" ")[-1]
        for cid in party["members"][1:]:
            first = self.entities[cid]["name"].split(" ")[0]
            self.entities[cid]["name"] = "%s %s" % (first, surname)

    # -- setup --------------------------------------------------------

    def _at(self, location):
        coords = self.coords[location]
        return (coords[0], coords[1] if len(coords) > 1 else 0.0)

    def _register_actions(self):
        reg = self.registry.register
        reg("seat_party", {"table": str}, 0.0, self._h_seat)
        reg("take_order", {"table": str}, 0.0, self._h_take_order)
        reg("cook_dish", {"order": str}, 0.0, self._h_cook)
        reg("serve_dish", {"order": str}, 0.0, self._h_serve)
        reg("pay_bill", {"table": str}, 0.0, self._h_pay)
        reg("order_dish", {"dish": str}, 0.0, self._h_order)
        reg("comp_dish", {"table": str}, 0.0, self._h_comp)
        reg("rush_order", {"order": str}, 0.0, self._h_rush)
        reg("recommend_wine", {"table": str}, 0.0, self._h_wine)
        reg("order_drink", {}, 0.0, self._h_drink)
        reg("cook_next", {}, 0.0, self._h_cook_next)
        reg("serve_next", {}, 0.0, self._h_serve_next)
        reg("seat_next", {}, 0.0, self._h_seat_next)
        reg("greet", {}, 0.0, self._h_greet)

    def attach(self, task_mgr):
        """Pump the runtime + tick the sim on a task manager."""
        try:
            m.attach(self.runtime, task_mgr)
        except ImportError:  # pragma: no cover - no Panda3D here
            def _pump(task):
                try:
                    self.runtime.pump()
                except m.Closed:
                    return DONE
                return CONT
            task_mgr.add(_pump, "npc-cortex-pump")

        def _tick(task):
            self.tick()
            return CONT

        task_mgr.add(_tick, "maison-cinq-tick")

    # -- action handlers (LLM- or player-facing) ------------------------

    def _new_order(self, table, dish=None, seat=None):
        self._oids += 1
        oid = "o%d" % self._oids
        item = dish or self.rng.choice(MENU)
        if isinstance(item, str):
            item = next((d for d in MENU if d["dish"] == item), MENU[0])
        self.orders[oid] = {"id": oid, "table": table, "seat": seat,
                            "dish": item["dish"],
                            "price": item["price"], "state": "ordered",
                            "progress": 0, "need": item["prep"],
                            "serve_in": 0}
        return oid

    def _h_seat(self, scenario, npc, params):
        table = self.tables.get(params.get("table", ""))
        if table and not table["guest"]:
            pid = self._waiting_party_for(table)
            if pid:
                self._seat(pid, table["id"])

    def _flash(self, kind, x, y):
        self.events.append({"kind": kind, "x": x, "y": y,
                            "tick": self.tick_count})
        del self.events[:-20]

    def _waiting_party_for(self, table):
        """First waiting party that fits, smallest fitting party first."""
        waiting = [p for p in self.parties.values()
                   if p["state"] == "waiting"
                   and len(p["members"]) <= table["seats"]]
        waiting.sort(key=lambda p: len(p["members"]))
        return waiting[0]["id"] if waiting else None

    def _free_table_for(self, party):
        free = [t for t in self.tables.values()
                if not t["guest"] and t["seats"] >= len(party["members"])]
        free.sort(key=lambda t: t["seats"])
        return free[0]["id"] if free else None

    def _seat(self, pid, table_id):
        table = self.tables[table_id]
        party = self.parties[pid]
        table["guest"] = party["members"][0]
        table["guests"] = list(party["members"])
        table["party"] = pid
        party["table"] = table_id
        self._set_party_state(party, "walking")
        x, y = self._place(table_id)
        for i, cid in enumerate(party["members"]):
            dx, dy = TABLE_SPOTS[i % len(TABLE_SPOTS)]
            self._move(cid, x + dx, y + dy)
        self._flash("seat", x, y)

    def _set_party_state(self, party, state):
        party["state"] = state
        for cid in party["members"]:
            if cid in self.flow:
                self.flow[cid]["state"] = state

    def _place(self, pid):
        coords = self.coords[pid]
        return (coords[0], coords[1])

    def _h_take_order(self, scenario, npc, params):
        table = self.tables.get(params.get("table", ""))
        if table and table["guest"]:
            self._take_orders_for_table(table)

    def _take_orders_for_table(self, table):
        """Every guest at the table orders (player/LLM shortcut)."""
        party = self.parties.get(table.get("party") or "")
        if not party or party["state"] not in ("seated", "ordering"):
            return False
        for cid in party["members"]:
            flow = self.flow[cid]
            if not flow.get("order"):
                flow["dish"] = flow["dish"] or self.rng.choice(MENU)["dish"]
                flow["order"] = self._new_order(table["id"], flow["dish"],
                                                seat=cid)
        self._release_waiter(party)
        self._set_party_state(party, "ordered")
        return True

    def _release_waiter(self, party):
        wid = party.get("waiter")
        if wid and wid in self.entities:
            self.entities[wid]["task"] = None
        party["waiter"] = None

    def _h_cook(self, scenario, npc, params):
        order = self.orders.get(params.get("order", ""))
        if order and order["state"] in ("ordered", "cooking"):
            order.update(state="ready", progress=order["need"])

    def _h_serve(self, scenario, npc, params):
        order = self.orders.get(params.get("order", ""))
        if order and order["state"] == "ready":
            order["state"] = "served"
            if order["table"] in self.coords:
                x, y = self._place(order["table"])
                self._flash("serve", x, y)
            for cid, flow in self.flow.items():
                if flow.get("order") == order["id"]:
                    flow["food"] = "served"
                    self._say(cid, "thanks", table=order["table"])

    def _h_pay(self, scenario, npc, params):
        table = self.tables.get(params.get("table", ""))
        if table and table["guest"]:
            party = self.parties.get(table.get("party") or "")
            if party:
                self._settle_party(party, tip=0)

    def _pinned(self, cid):
        """A guest the player chatted with lately never quits mid-talk."""
        for msg in self.chats.get(cid, {}).get("messages", []):
            if msg.get("by") == "you" and \
                    self.tick_count - msg.get("tick", 0) <= CHAT_PIN_WINDOW:
                return True
        return False

    def _free_seats(self):
        return sum(t["seats"] for t in self.tables.values()
                   if not t["guest"])

    def _settle_party(self, party, tip):
        self._memorize_service(party)
        total = 0
        for cid in party["members"]:
            flow = self.flow.get(cid, {})
            order = self.orders.get(flow.get("order") or "")
            if order:
                total += order["price"]
                order["state"] = "paid"
        self.stats["revenue"] += total + tip
        self.stats["served"] += len(party["members"])
        waited = party.get("waited", 0)
        self.stats["satisfaction"].append(5 if waited < 200 else
                                          4 if waited < 450 else
                                          3 if waited < 700 else 2)
        table_id = party.get("table")
        if table_id and table_id in self.coords:
            x, y = self._place(table_id)
            self._flash("pay", x, y)
        if table_id and table_id in self.tables:
            self.tables[table_id].update(guest=None, guests=[], party=None)
        party["table"] = None
        for cid in party["members"]:
            self.flow[cid].update(table=None, order=None)
        if any(self._pinned(c) for c in party["members"]):
            # Paid up, but mid-conversation: linger at the bar, table freed.
            self._set_party_state(party, "lingering")
            for i, cid in enumerate(party["members"]):
                x, y = LINGER_SPOTS[i % len(LINGER_SPOTS)]
                self._move(cid, x, y)
            return
        self._set_party_state(party, "leaving")
        for i, cid in enumerate(party["members"]):
            self._move(cid, EXIT_SPOT[0] + i * 0.8, EXIT_SPOT[1])

    def _h_order(self, scenario, npc, params):
        oid = self._new_order("bar", params.get("dish", ""))
        self.player_tab["orders"].append(oid)
        self.orders[oid]["state"] = "cooking"

    def _h_comp(self, scenario, npc, params):
        table = self.tables.get(params.get("table", ""))
        if table and table["guest"]:
            self.stats["satisfaction"].append(5)

    def _h_rush(self, scenario, npc, params):
        order = self.orders.get(params.get("order", ""))
        if order and order["state"] in ("ordered", "cooking"):
            order["progress"] = order["need"]

    def _h_wine(self, scenario, npc, params):
        self.stats["revenue"] += 12

    def _h_drink(self, scenario, npc, params):
        self.stats["revenue"] += 8
        self.stats["satisfaction"].append(4)

    def _h_cook_next(self, scenario, npc, params):
        for order in self.orders.values():
            if order["state"] in ("ordered", "cooking"):
                order.update(state="ready", progress=order["need"])
                return

    def _h_serve_next(self, scenario, npc, params):
        for order in self.orders.values():
            if order["state"] == "ready" and order["table"] != "bar":
                self._h_serve(scenario, npc, {"order": order["id"]})
                return

    def _h_seat_next(self, scenario, npc, params):
        for table in sorted(self.tables.values(),
                            key=lambda t: t["seats"]):
            if not table["guest"]:
                pid = self._waiting_party_for(table)
                if pid:
                    self._seat(pid, table["id"])
                    return

    def _h_greet(self, scenario, npc, params):
        for party in self.parties.values():
            if party["state"] == "waiting":
                party["patience"] = min(QUEUE_PATIENCE,
                                        party["patience"] + GREET_BOOST)

    # -- player (role-gated) --------------------------------------------

    def set_role(self, role):
        if role not in ROLE_ACTIONS:
            raise ValueError("role must be one of %s" % sorted(ROLE_ACTIONS))
        self.player.role = role
        self.entities["you"]["role"] = role
        x, y = self._at(ROLE_SPOT[role])
        self.entities["you"].update(tx=x, ty=y)
        return role

    def available_actions(self):
        if self.mode != "active":
            return []
        return list(ROLE_ACTIONS[self.player.role])

    def player_act(self, action, params):
        """Immediate, validated player action (active mode only)."""
        if self.mode != "active":
            raise PermissionError("passive mode: watching only")
        if action not in ROLE_ACTIONS[self.player.role]:
            raise PermissionError("role %r cannot %r"
                                  % (self.player.role, action))
        if action == "order_dish":
            dish = params.get("dish", "")
            self._h_order(self.scenario, None, {"dish": dish})
            return {"ok": True, "message": "Ordered %s at the bar." % dish}
        elif action == "pay_bill":
            total = sum(self.orders[o]["price"] for o in self.player_tab["orders"]
                        if self.orders[o]["state"] != "paid")
            for oid in self.player_tab["orders"]:
                self.orders[oid]["state"] = "paid"
            self.stats["revenue"] += total
            self.player_tab = {"orders": [], "paid": total}
            return {"paid": total,
                    "message": "Paid €%d — tab closed." % total if total
                    else "Nothing on your tab."}
        elif action == "take_order":
            table = self.tables.get(params.get("table", ""))
            if not table or not table["guest"]:
                return {"ok": True, "ordered": False,
                        "message": "Nobody to take an order from there."}
            if self._take_orders_for_table(table):
                return {"ok": True, "ordered": True,
                        "message": "Order taken at %s." % table["id"]}
            return {"ok": True, "ordered": False,
                    "message": "They already ordered at %s." % table["id"]}
        elif action == "serve_dish":
            order = self.orders.get(params.get("order", ""))
            if order and order["state"] == "ready":
                self._h_serve(self.scenario, None, params)
                self.stats["revenue"] += 5  # tip for swift service
                return {"tip": 5,
                        "message": "Served %s (+€5 tip)." % order["id"]}
            return {"tip": 0,
                    "message": "Nothing ready to serve for %s."
                    % params.get("order", "?")}
        elif action == "cook_dish":
            order = self.orders.get(params.get("order", ""))
            if order and order["state"] in ("ordered", "cooking"):
                self._h_cook(self.scenario, None, params)
                return {"ok": True,
                        "message": "%s fired and ready." % order["id"]}
            return {"ok": True, "message": "No such open order."}
        elif action == "comp_dish":
            table = self.tables.get(params.get("table", ""))
            if table and table["guest"]:
                self._h_comp(self.scenario, None, params)
                return {"ok": True,
                        "message": "Dessert on the house at %s." % table["id"]}
            return {"ok": True, "message": "That table is empty."}
        elif action == "rush_order":
            order = self.orders.get(params.get("order", ""))
            if order and order["state"] in ("ordered", "cooking"):
                self._h_rush(self.scenario, None, params)
                return {"ok": True,
                        "message": "%s rushed to the pass." % order["id"]}
            return {"ok": True, "message": "No such open order."}
        elif action == "order_drink":
            self._h_drink(self.scenario, None, params)
            return {"ok": True, "message": "A drink appears (€8)."}
        elif action == "cook_next":
            before = [o["id"] for o in self.orders.values()
                      if o["state"] == "ready"]
            self._h_cook_next(self.scenario, None, params)
            after = [o["id"] for o in self.orders.values()
                     if o["state"] == "ready"]
            done = [oid for oid in after if oid not in before]
            return {"ok": True, "message": "Fired %s." % done[0] if done
                    else "No open orders."}
        elif action == "serve_next":
            ready = [o for o in self.orders.values()
                     if o["state"] == "ready" and o["table"] != "bar"]
            if ready:
                self._h_serve(self.scenario, None, {"order": ready[0]["id"]})
                self.stats["revenue"] += 5
                return {"tip": 5, "message": "Served %s (+€5 tip)."
                        % ready[0]["id"]}
            return {"tip": 0, "message": "Nothing ready to serve."}
        elif action == "seat_next":
            waiting = sum(1 for p in self.parties.values()
                          if p["state"] == "waiting")
            free = sum(1 for t in self.tables.values() if not t["guest"])
            if waiting and free:
                self._h_seat_next(self.scenario, None, params)
                return {"ok": True, "message": "Party seated."}
            return {"ok": True, "message": "Nobody to seat." if not waiting
                    else "No free table."}
        elif action == "greet":
            waiting = [p for p in self.parties.values()
                       if p["state"] == "waiting"]
            self._h_greet(self.scenario, None, params)
            return {"ok": True, "message": "Greeted %d parties." % len(waiting)
                    if waiting else "Nobody waiting."}
        return {"ok": True}

    def move_player(self, x, y):
        """Free movement (active mode only); clamped to the floor."""
        if self.mode != "active":
            raise PermissionError("passive mode: watching only")
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            raise ValueError("x and y must be numbers")
        self.entities["you"].update(tx=min(40.0, max(0.0, x)),
                                    ty=min(24.0, max(0.0, y)))

    def nearby_utilities(self):
        """Functional utilities in reach, with prefilled actions."""
        you = self.entities["you"]
        spots = list(UTILITIES)
        for table in self.tables.values():
            x, y = self._place(table["id"])
            spots.append({"id": table["id"], "label": "Table " + table["id"],
                          "x": x, "y": y, "radius": 4.0,
                          "table": table["id"]})
        role = self.player.role
        out = []
        for spot in spots:
            dist = distance((you["x"], you["y"]), (spot["x"], spot["y"]))
            if dist > spot["radius"]:
                continue
            actions = []
            if spot["id"] == "bar" and role in ("customer", "manager"):
                actions.append({"action": "order_drink", "label": "Order drink",
                                "params": {}})
            if spot["id"] == "pass" and role == "chef":
                actions.append({"action": "cook_next", "label": "Fire next dish",
                                "params": {}})
            if spot["id"] == "pass" and role == "waiter":
                actions.append({"action": "serve_next",
                                "label": "Run next dish", "params": {}})
            if spot["id"] == "host_stand" and role == "manager":
                actions.append({"action": "seat_next", "label": "Seat party",
                                "params": {}})
                actions.append({"action": "greet", "label": "Greet line",
                                "params": {}})
            if spot.get("table"):
                table = self.tables[spot["table"]]
                if table["guest"] and role == "waiter":
                    actions.append({"action": "take_order", "label": "Take order",
                                    "params": {"table": table["id"]}})
                if table["guest"] and role == "manager":
                    actions.append({"action": "comp_dish",
                                    "label": "Comp dessert",
                                    "params": {"table": table["id"]}})
            if actions:
                out.append({"id": spot["id"], "label": spot["label"],
                            "distance": round(dist, 1), "actions": actions})
        return out

    def talk(self, to_id, text):
        if self.mode != "active":
            raise PermissionError("passive mode: watching only")
        if to_id != "you" and not any(n.id == to_id for n in self.scenario.npcs):
            raise KeyError("unknown person %r" % to_id)
        tagged = "[lang:%s] %s" % (self.lang, text)
        self._last_player_talk = self.tick_count
        self._record_speech("you", text)
        thread = self.chats.setdefault(to_id, {"known": False, "messages": []})
        thread["messages"].append({"by": "you", "text": text,
                                   "tick": self.tick_count})
        del thread["messages"][:-50]
        self._save_chats()
        # Submit last: the reply worker may resolve immediately, and the
        # player's line must already be first in the thread.
        try:
            self.runtime.submit(m.Event(kind="direct_message", npc_id=to_id,
                                        speaker_id="you", text=tagged))
        except (m.Overloaded, m.Closed):
            thread["messages"].pop()  # unsent: leave no trace behind
            with self._spoken_lock:
                if self.spoken and self.spoken[-1]["by"] == "you":
                    self.spoken.pop()
                if self.transcript and self.transcript[-1]["by"] == "you":
                    self.transcript.pop()
            self._save_chats()
            raise

    # -- tick -------------------------------------------------------------

    def tick(self):
        self.tick_count += 1
        tick = self.tick_count
        self.stats["tick"] = tick
        self._flow(tick)
        self._kitchen()
        self._move_entities()
        self._sync_positions()
        self._spawn_in -= 1
        if self._spawn_in <= 0:
            self._spawn_in = SPAWN_EVERY
            # Never more guests inside than seats at free tables (a new
            # party holds up to 4, hence the headroom).
            if len(self.flow) + 4 <= self._free_seats():
                self._mint_party()
        self._chatter_in -= 1
        if self._chatter_in <= 0:
            self._chatter_in = (CHATTER_EVERY
                                + self.rng.randint(-30, 30))
            self._chatter()
        self._drain_listening()
        self._drain_lines()
        self._initiative_in -= 1
        if self._initiative_in <= 0:
            self._initiative_in = (INITIATIVE_EVERY
                                   + self.rng.randint(-30, 30))
            self._initiative()
        self._learn_in -= 1
        if self._learn_in <= 0:
            self._learn_in = LEARN_EVERY
            self._learn()

    def _mint_customer(self):
        """Legacy solo arrival; the floor mints parties (see below)."""
        return self._mint_party(kind="solo")

    def _mint_party(self, kind=None):
        """Create a brand-new party on the go via the forge."""
        from npc_cortex.forge.schemas import Quest, QuestNPC

        if kind is None:
            kinds, weights = zip(*[(k, w) for k, _, _, w in PARTY_KINDS])
            kind = self.rng.choices(kinds, weights=weights)[0]
        _, lo, hi, _ = next(k for k in PARTY_KINDS if k[0] == kind)
        size = self.rng.randint(lo, hi)
        gtype = self.game.types["customer"]
        members = []
        quests_npcs = []
        for _ in range(size):
            self._customer_seq += 1
            cid = "c%d" % self._customer_seq
            members.append(cid)
            quests_npcs.append(QuestNPC(id=cid, type="customer",
                                        mode="generic",
                                        fixed={"location": "entrance"},
                                        open=list(gtype.open)))
        quest = Quest(
            id="flow", title="Arrival", scenario="Guests arrive.",
            time=self.game.time_current or "tonight", latency_budget_ms=1500,
            dialogue_intensity="low", npcs=quests_npcs)
        report = NPCGenerator(self.game, [quest],
                              seed=1000 + self._customer_seq).run(
                                  self._out_dir / "flow", refresh=True)
        x, y = self._at("entrance")
        for cid in members:
            spec = report.by_id(cid)
            self.specs[cid] = spec
            self._spec_home[cid] = quest.id
            self.scenario.npcs.append(
                spec.to_runtime_npc(self.game, horizon=12.0,
                                    implication=0.7))
            self.entities[cid] = {
                "id": cid, "name": spec.name, "kind": "customer",
                "role": "customer", "x": float(x), "y": float(y),
                "tx": float(x), "ty": float(y), "speed": 4.5,
                "state": "idle", "table": None, "party": None,
                "task": None,
            }
        self._party_seq += 1
        pid = "p%d" % self._party_seq
        self.parties[pid] = {
            "id": pid, "kind": kind, "members": members,
            "state": "away", "timer": 5, "table": None,
            "waiter": None, "turn": 0, "turn_timer": 0,
            "patience": QUEUE_PATIENCE, "waited": 0,
        }
        for cid in members:
            self.flow[cid] = {"state": "away", "timer": 5, "table": None,
                              "order": None, "dish": None, "food": None,
                              "party": pid}
            self.entities[cid]["party"] = pid
        if kind == "family":
            self._share_surname(pid)
        return pid

    def _remove_party(self, pid):
        """Leavers are gone for good: out of the runtime and the floor."""
        party = self.parties.pop(pid, None)
        if not party:
            return
        gone = set(party["members"])
        self.scenario.npcs = [n for n in self.scenario.npcs
                              if n.id not in gone]
        for cid in gone:
            self.entities.pop(cid, None)
            self.flow.pop(cid, None)
            self.specs.pop(cid, None)
        # Chat threads stay: the player's discussion record survives.

    def _say(self, npc_id, stage, table=None, dish=None, dishes=None,
             to_you=False):
        """One staged line through the dialogue engine (LLM-voiced)."""
        text = "[lang:%s] stage:%s" % (self.lang, stage)
        if table:
            text += " table:%s" % table
        if dish:
            text += " dish:%s" % dish
        if to_you:
            text += " to:you"
        if dishes:
            # completion is async (task may clear first): stash the slots
            self._stage_ctx[npc_id] = {"dishes": dishes}
        try:
            self.runtime.submit(m.Event(kind="tick", npc_id=npc_id,
                                        text=text))
        except (m.Overloaded, m.Closed):
            pass

    def _at_target(self, cid, tol=WALK_TOL):
        entity = self.entities[cid]
        return abs(entity["x"] - entity["tx"]) + abs(entity["y"] - entity["ty"]) < tol

    def _free_waiter(self):
        for wid in ("nina", "omar"):
            if self.entities[wid]["task"] is None:
                return wid
        return None

    def _storm_out(self, party):
        for i, cid in enumerate(party["members"]):
            self._move(cid, EXIT_SPOT[0] + i * 0.8, EXIT_SPOT[1])
        table_id = party.get("table")
        if table_id and table_id in self.tables:
            self.tables[table_id].update(guest=None, guests=[], party=None)
        party["table"] = None
        self._release_waiter(party)
        self._set_party_state(party, "leaving")
        self.stats["lost"] += 1
        self.stats["satisfaction"].append(1)

    def _flow(self, tick):
        for pid, party in list(self.parties.items()):
            state = party["state"]
            if state == "away":
                party["timer"] -= 1
                if party["timer"] <= 0:
                    if len(self.flow) > self._free_seats():
                        party["timer"] = 30  # house full: try the door later
                        continue
                    party["patience"] = QUEUE_PATIENCE
                    party["waited"] = 0
                    self._set_party_state(party, "waiting")
                    if not party.get("welcomed"):
                        party["welcomed"] = True
                        self._say("theo", "welcome")
                    queue = sum(1 for p in self.parties.values()
                                if p["state"] == "waiting")
                    for i, cid in enumerate(party["members"]):
                        self._move(cid, QUEUE_SPOT[0] + queue * 2.0 + i * 0.8,
                                   QUEUE_SPOT[1] + (i % 2) * 0.8)
            elif state == "waiting":
                party["patience"] -= 1
                party["waited"] += 1
                if party["patience"] <= 0:
                    if any(self._pinned(c) for c in party["members"]):
                        party["patience"] = 1  # pinned: hold, don't storm
                    else:
                        self._storm_out(party)  # storm out, gone for good
                elif tick % 10 == 0:
                    table_id = self._free_table_for(party)
                    if table_id:
                        self._seat(pid, table_id)
            elif state == "walking":
                if all(self._at_target(cid) for cid in party["members"]):
                    party["timer"] = BROWSE_TICKS
                    party["patience"] = SEAT_PATIENCE
                    self._set_party_state(party, "seated")
            elif state == "seated":
                party["timer"] -= 1
                party["patience"] -= 1
                # NOTE: browsing/ordering are the experience, not waiting;
                # only queue time counts against satisfaction.
                if party["patience"] <= 0:
                    if any(self._pinned(c) for c in party["members"]):
                        party["patience"] = 1  # pinned: hold, don't storm
                    else:
                        self._storm_out(party)  # ignored: walk out
                elif party["timer"] <= 0:
                    wid = self._free_waiter()
                    if wid:
                        party["waiter"] = wid
                        party["turn"] = 0
                        party["turn_timer"] = DISCUSS_GAP
                        self.entities[wid]["task"] = {"pid": pid}
                        x, y = self._place(party["table"])
                        self._move(wid, x, y - 2.2)
                        self._set_party_state(party, "ordering")
                    else:
                        party["timer"] = 40  # retry shortly
            elif state == "ordering":
                self._service(party)
            elif state == "ordered":
                if all(self.flow[c]["food"] == "served"
                       for c in party["members"]):
                    party["timer"] = EAT_TICKS
                    self._set_party_state(party, "eating")
            elif state == "eating":
                party["timer"] -= 1
                if party["timer"] <= 0:
                    party["timer"] = PAY_TICKS
                    self._set_party_state(party, "paying")
                    self._say(party["members"][0], "bye",
                              table=party["table"])
            elif state == "paying":
                party["timer"] -= 1
                if party["timer"] <= 0:
                    self._settle_party(party, tip=0)
            elif state == "lingering":
                if all(self._at_target(c) for c in party["members"]) \
                        and not any(self._pinned(c)
                                    for c in party["members"]):
                    self._say(party["members"][0], "bye")
                    self._set_party_state(party, "leaving")
                    for i, cid in enumerate(party["members"]):
                        self._move(cid, EXIT_SPOT[0] + i * 0.8, EXIT_SPOT[1])
            elif state == "leaving":
                if all(abs(self.entities[c]["x"] - EXIT_SPOT[0]) < 1.5
                       for c in party["members"]):
                    self._remove_party(pid)

    def _service(self, party):
        """Waiter discussion at the table, one turn per window."""
        wid = party.get("waiter")
        if not wid or wid not in self.entities:
            wid = self._free_waiter()
            if not wid:
                return
            party["waiter"] = wid
            self.entities[wid]["task"] = {"pid": party["id"]}
            x, y = self._place(party["table"])
            self._move(wid, x, y - 2.2)
            return
        if not self._at_target(wid):
            return  # still walking over
        party["turn_timer"] -= 1
        if party["turn_timer"] > 0:
            return
        party["turn_timer"] = DISCUSS_GAP
        members = party["members"]
        turn = party["turn"]
        table = party["table"]
        if turn == 0:
            self._say(wid, "greet", table=table)
        elif 1 <= turn <= len(members):
            cid = members[turn - 1]
            dish = self.rng.choice(MENU)["dish"]
            self.flow[cid]["dish"] = dish
            self._say(cid, "choice", table=table, dish=dish)
        else:
            dishes = ", ".join("the " + self.flow[c]["dish"]
                               for c in members)
            self._say(wid, "confirm", table=table, dishes=dishes)
            for cid in members:
                flow = self.flow[cid]
                flow["order"] = self._new_order(table, flow["dish"], seat=cid)
            party["served_by"] = wid
            self._release_waiter(party)
            self._set_party_state(party, "ordered")
            return
        party["turn"] += 1

    def _drain_lines(self):
        """Deliver scheduled follow-up lines whose window arrived."""
        due = [p for p in self._pending_lines if p[0] <= self.tick_count]
        self._pending_lines = [p for p in self._pending_lines
                               if p[0] > self.tick_count]
        for _, npc, stage, table, dish, to_you in due:
            if npc in self.entities:
                self._say(npc, stage, table=table, dish=dish, to_you=to_you)

    def _later(self, delay, npc, stage, table=None, dish=None, to_you=False):
        self._pending_lines.append((self.tick_count + delay, npc, stage,
                                    table, dish, to_you))

    # -- initiative: NPCs choosing to speak --------------------------------

    def _initiative(self):
        """One NPC with a motive speaks (state-driven, LLM-voiced)."""
        if self._motive_complaint():
            return
        if self._motive_checkin():
            return
        self._motive_player()

    def _motive_complaint(self):
        """Long-waiting guests grumble (cooldown per party)."""
        for party in self.parties.values():
            if party["state"] != "waiting" or party["waited"] < 400:
                continue
            if self.tick_count - party.get("complained_at", -9999) < 300:
                continue
            party["complained_at"] = self.tick_count
            cid = self.rng.choice(party["members"])
            self._say(cid, "complaint")
            return True
        return False

    def _motive_checkin(self):
        """A free waiter checks back on a mid-meal table, once."""
        for party in self.parties.values():
            if party["state"] != "eating" or party.get("checked"):
                continue
            if party["timer"] >= EAT_TICKS // 2:
                continue
            wid = self._free_waiter()
            if not wid:
                return False
            party["checked"] = True
            x, y = self._place(party["table"])
            self.entities[wid]["task"] = {"pid": party["id"],
                                          "until": self.tick_count + 120}
            self._move(wid, x, y - 2.2)
            self._say(wid, "checkin", table=party["table"])
            cid = self.rng.choice(party["members"])
            self._later(DISCUSS_GAP, cid, "fine",
                        table=party["table"],
                        dish=self.flow[cid].get("dish"))
            self._later(DISCUSS_GAP + 100, wid, "bye", table=party["table"])
            return True
        return False

    def _motive_player(self):
        """Someone near the idle player starts a conversation."""
        if self.mode != "active":
            return False
        if self.tick_count - self._last_player_talk < PLAYER_IDLE_TICKS:
            return False
        if self.tick_count - self._player_idle_cd < PLAYER_IDLE_TICKS:
            return False
        you = self.entities["you"]
        near = []
        for eid, entity in self.entities.items():
            if eid == "you" or entity.get("kind") == "player":
                continue
            dist = ((entity["x"] - you["x"]) ** 2
                    + (entity["y"] - you["y"]) ** 2) ** 0.5
            if dist <= 6.0:
                near.append((entity.get("kind") == "staff", dist, eid))
        if not near:
            return False
        near.sort(key=lambda t: (not t[0], t[1]))
        self._player_idle_cd = self.tick_count
        self._say(near[0][2], "approach", to_you=True)
        return True

    # -- continuous updates: lived memory back into the NPCs ----------------

    def _learn(self):
        """Fold the night so far into staff specs + artifacts (throttled)."""
        for sid, entity in self.entities.items():
            if entity.get("kind") != "staff":
                continue
            spec = self.specs.get(sid)
            if spec is None:
                continue
            try:
                spec.absorb(self.runtime.export_memory(sid))
                for heard in self._heard.get(sid, ()):
                    spec.short_memory.append({
                        "text": '"%s" -- %s' % (heard["text"], heard["by"]),
                        "tags": ["overheard"]})
                del spec.short_memory[:-20]
                home = self._spec_home.get(sid, "rush")
                spec.write_artifacts(self._out_dir / home)
            except Exception:
                continue  # learning never breaks the night

    def _memorize_service(self, party):
        """The serving waiter keeps the table as a long-term fact."""
        wid = party.get("served_by")
        spec = self.specs.get(wid or "")
        if spec is None:
            return
        names = " and ".join(
            self.entities[c]["name"].split(" ")[0] for c in party["members"])
        dishes = ", ".join("the " + (self.flow[c].get("dish") or "special")
                           for c in party["members"])
        mood = "loved it" if party.get("waited", 999) < 200 else \
            "had a good night" if party.get("waited", 999) < 450 else \
            "waited too long"
        spec.long_memory.append({
            "fact": "Served %s (%s) at table %s: %s. They %s."
                    % (names, party["kind"],
                       (party.get("table") or "t?")[1:], dishes, mood)})
        del spec.long_memory[:-30]

    def _kitchen(self):
        cooking = [o for o in self.orders.values() if o["state"] == "cooking"]
        for order in self.orders.values():
            if order["state"] == "ordered" and len(cooking) < 2:
                order["state"] = "cooking"
                cooking.append(order)
        for order in cooking:
            order["progress"] += 1
            if order["progress"] >= order["need"]:
                order["state"] = "ready"
                order["serve_in"] = SERVE_DELAY
        for order in self.orders.values():
            if order["state"] == "ready" and order["table"] != "bar":
                order["serve_in"] -= 1
                if order["serve_in"] <= 0:
                    self._h_serve(self.scenario, None, {"order": order["id"]})

    def _move(self, cid, x, y):
        self.entities[cid].update(tx=float(x), ty=float(y))

    def _move_entities(self):
        for eid, entity in self.entities.items():
            dx, dy = entity["tx"] - entity["x"], entity["ty"] - entity["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 0.05:
                continue
            step = min(dist, entity["speed"] / TICK_HZ)
            entity["x"] += dx / dist * step
            entity["y"] += dy / dist * step
        # free waiters drift between pass and busy tables; tasked
        # waiters keep the targets the service flow gave them
        busy = [t for t in self.tables.values() if t["guest"]]
        for wid in ("nina", "omar"):
            entity = self.entities[wid]
            task = entity.get("task")
            if task:
                if task.get("until", 10 ** 18) <= self.tick_count:
                    entity["task"] = None  # timed errand over: back to drift
                else:
                    continue
            if abs(entity["x"] - entity["tx"]) + abs(entity["y"] - entity["ty"]) < 0.5:
                target = self.rng.choice(busy)["id"] if busy else "dining_hall"
                x, y = self._place(target) if target in self.coords else self._at(target)
                entity.update(tx=x, ty=y)

    def _sync_positions(self):
        by_id = {n.id: n for n in self.scenario.npcs}
        for eid, entity in self.entities.items():
            if eid in by_id:
                by_id[eid].position = (entity["x"], entity["y"])
        you = self.entities["you"]
        self.player.position = (you["x"], you["y"])

    def _chatter(self):
        present = [cid for cid, f in self.flow.items()
                   if f["state"] not in ("away", "leaving")]
        pool = ["celeste", "theo", "nina", "omar", "auguste", "leo",
                "priya"] + present
        npc_id = self.rng.choice(pool)
        try:
            self.runtime.submit(m.Event(kind="tick", npc_id=npc_id,
                                        text="[lang:%s]" % self.lang))
        except (m.Overloaded, m.Closed):
            pass

    def _spoken_since(self, cursor):
        with self._spoken_lock:
            return list(self.spoken[max(0, cursor):])

    # -- snapshot -----------------------------------------------------------

    def state(self, delivered_since=0):
        entities = []
        for entity in self.entities.values():
            if entity["id"] == "you" and self.mode != "active":
                continue
            spec = self.specs.get(entity["id"])
            flow = self.flow.get(entity["id"], {})
            party = self.parties.get(flow.get("party") or "")
            entities.append({
                "id": entity["id"], "name": entity["name"],
                "kind": entity["kind"], "role": entity["role"],
                "x": round(entity["x"], 1), "y": round(entity["y"], 1),
                "state": entity["state"],
                "flow": flow.get("state"),
                "group": party["kind"] if party else None,
                "known": self._player_knows(entity["id"]),
                "languages": spec.languages if spec else ["english"],
            })
        tables = []
        for table in self.tables.values():
            x, y = self._place(table["id"])
            tables.append({"id": table["id"], "seats": table["seats"],
                           "x": x, "y": y, "guest": table["guest"],
                           "guests": list(table["guests"])})
        satisfaction = self.stats["satisfaction"]
        return {
            "mode": self.mode, "role": self.player.role, "lang": self.lang,
            "tick": self.tick_count,
            "entities": entities, "tables": tables,
            "orders": [dict(o) for o in self.orders.values()][-12:],
            "waiting": sum(1 for f in self.flow.values()
                           if f["state"] == "waiting"),
            "stats": {"revenue": self.stats["revenue"],
                      "served": self.stats["served"],
                      "lost": self.stats["lost"],
                      "rating": round(sum(satisfaction) / len(satisfaction), 1)
                      if satisfaction else 5.0},
            "bubbles": [dict(b) for b in self._spoken_since(delivered_since)][-8:],
            "delivered_cursor": len(self.spoken),
            "actions": self.available_actions(),
            "menu": [d["dish"] for d in MENU],
            "events": [dict(e) for e in self.events[-10:]],
            "transcript": self._transcript_tail(),
            "nearby": self.nearby_utilities(),
            "chats": self._chat_threads(),
        }

    def _chat_threads(self):
        """Player chat record: per-person threads, strangers unnamed."""
        threads = {}
        for nid, thread in self.chats.items():
            if nid == "you" or not thread.get("messages"):
                continue
            entity = self.entities.get(nid, {})
            name = entity.get("name") or nid
            threads[nid] = {
                "name": name if thread.get("known") else None,
                "known": bool(thread.get("known")),
                "messages": [dict(m) for m in thread["messages"][-15:]],
            }
        return threads

    def _transcript_tail(self, limit: int = 30) -> list:
        with self._spoken_lock:
            entries = list(self.transcript[-limit:])
        self._fill_hearers_for(entries)
        return [dict(e) for e in entries]

    def _fill_hearers_for(self, entries):
        for entry in entries:
            if entry["heard_by"] is not None:
                continue
            me = self.entities.get(entry["by"])
            if not me:
                entry["heard_by"] = []
                continue
            heard = []
            for eid, entity in self.entities.items():
                if eid == entry["by"]:
                    continue
                horizon = 1000.0 if eid == "you" else 12.0
                if distance((entity["x"], entity["y"]),
                            (me["x"], me["y"])) <= horizon:
                    heard.append(eid)
            entry["heard_by"] = sorted(heard)

    def close(self):
        self.runtime.close()
