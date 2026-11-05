"""Restaurant game tests: forge pack, sim flow, roles, server API."""

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

GAME = Path(__file__).resolve().parent.parent.parent / "games" / "restaurant"
sys.path.insert(0, str(GAME))
sys.path.insert(0, str(GAME.parent.parent / "src"))

from provider import (LLMNotConfigured, RestaurantProvider, build_provider,  # noqa: E402
                     key_status)
from server import Game, _Handler  # noqa: E402
from sim import DISCUSS_GAP, EAT_TICKS, MENU, PAY_TICKS, ROLE_ACTIONS, Sim, make_task_manager  # noqa: E402
from npc_cortex.forge import evaluate, load_game, load_quest  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _sim(tmp_path):
    return Sim(RestaurantProvider(inner=_FakeInner()),
               out_dir=tmp_path / "out")


def _stepped(sim, ticks):
    tm = make_task_manager()
    sim.attach(tm)
    for _ in range(ticks):
        tm.step()
    return sim


def test_forge_pack_passes_clarity_gate():
    game = load_game(GAME / "forge" / "game-description.toml")
    for name in ("game-quest-1.toml", "game-quest-2.toml"):
        quest = load_quest(GAME / "forge" / name)
        report = evaluate(game, quest)
        assert report.errors == [], (name, str(report))
        assert report.passed, (name, str(report))


def test_dinner_service_flows_and_earns(tmp_path):
    sim = _stepped(_sim(tmp_path), 3000)
    try:
        stats = sim.state()["stats"]
        assert stats["served"] >= 1
        assert stats["revenue"] > 0
        assert 1.0 <= stats["rating"] <= 5.0
    finally:
        sim.close()


def test_roles_gate_actions(tmp_path):
    sim = _sim(tmp_path)
    try:
        for role, actions in ROLE_ACTIONS.items():
            assert sim.set_role(role) == role
            assert sim.available_actions() == actions
        with pytest.raises(ValueError):
            sim.set_role("pirate")
        sim.set_role("chef")
        with pytest.raises(PermissionError):
            sim.player_act("pay_bill", {})
        sim.mode = "passive"
        assert sim.available_actions() == []
        with pytest.raises(PermissionError):
            sim.player_act("cook_dish", {"order": "o1"})
        with pytest.raises(PermissionError):
            sim.talk("auguste", "hi")
    finally:
        sim.close()


def test_customer_orders_and_pays(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.set_role("customer")
        sim.player_act("order_dish", {"dish": "Duck Confit"})
        assert len(sim.player_tab["orders"]) == 1
        out = sim.player_act("pay_bill", {})
        assert out["paid"] == 38
        assert sim.stats["revenue"] == 38
    finally:
        sim.close()


def test_talk_delivers_speech(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim.talk("auguste", "bonsoir chef")
        for _ in range(200):  # replies resolve on worker threads
            tm.step()
            if sim.gateway.delivered:
                break
            time.sleep(0.01)
        assert sim.gateway.delivered, "no reply arrived"
        assert sim.gateway.delivered[-1][0] == "you"
    finally:
        sim.close()


def test_chatter_carries_current_language(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.lang = "arabic"
        seen = []
        real_submit = sim.runtime.submit
        sim.runtime.submit = lambda event: seen.append(event)
        try:
            sim._chatter()
        finally:
            sim.runtime.submit = real_submit
        assert seen and "[lang:arabic]" in (seen[0].text or "")
    finally:
        sim.close()


def test_actions_report_outcomes_not_silence(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.set_role("waiter")
        out = sim.player_act("take_order", {"table": "t1"})
        assert out["ordered"] is False and "Nobody" in out["message"]
        out = sim.player_act("serve_dish", {"order": "o999"})
        assert out["tip"] == 0 and "Nothing ready" in out["message"]
        out = sim.player_act("take_order", {"table": "nope"})
        assert out["ordered"] is False
    finally:
        sim.close()


def test_events_feed_canvas_flashes(tmp_path):
    sim = _stepped(_sim(tmp_path), 2500)
    try:
        kinds = {e["kind"] for e in sim.state()["events"]}
        assert kinds & {"seat", "serve", "pay"}, kinds
        for event in sim.state()["events"]:
            assert set(event) == {"kind", "x", "y", "tick"}
    finally:
        sim.close()


def test_transcript_records_who_heard(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim.talk("auguste", "bonsoir chef")
        replies = []
        for _ in range(200):  # replies resolve on worker threads
            tm.step()
            replies = [t for t in sim.state()["transcript"]
                       if t["by"] == "auguste"]
            if replies:
                break
            time.sleep(0.01)
        assert replies, "no reply from auguste recorded"
        line = replies[-1]
        assert "you" in line["heard_by"]  # the player hears everything
        assert set(line) == {"tick", "by", "text", "heard_by"}
    finally:
        sim.close()


def test_free_movement_clamped_and_gated(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.move_player(10, 10)
        assert sim.entities["you"]["tx"] == 10
        sim.move_player(999, -5)
        assert sim.entities["you"]["tx"] == 40.0
        assert sim.entities["you"]["ty"] == 0.0
        sim.mode = "passive"
        with pytest.raises(PermissionError):
            sim.move_player(5, 5)
    finally:
        sim.close()


def test_utilities_offer_contextual_actions(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.set_role("customer")
        sim.entities["you"].update(x=32.0, y=4.0, tx=32.0, ty=4.0)
        nearby = {u["id"] for u in sim.nearby_utilities()}
        assert "bar" in nearby
        bar = next(u for u in sim.nearby_utilities() if u["id"] == "bar")
        assert [a["action"] for a in bar["actions"]] == ["order_drink"]
        sim.entities["you"].update(x=20.0, y=12.0, tx=20.0, ty=12.0)
        assert "bar" not in {u["id"] for u in sim.nearby_utilities()}
    finally:
        sim.close()


def test_utility_actions_work(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.set_role("customer")
        out = sim.player_act("order_drink", {})
        assert sim.stats["revenue"] == 8 and "€8" in out["message"]
        sim.set_role("manager")
        out = sim.player_act("greet", {})
        assert "Greeted" in out["message"] or "Nobody" in out["message"]
        out = sim.player_act("seat_next", {})
        assert "message" in out
        sim.set_role("chef")
        assert "message" in sim.player_act("cook_next", {})
        sim.set_role("waiter")
        assert "message" in sim.player_act("serve_next", {})
    finally:
        sim.close()


def test_customers_minted_on_the_go_and_leavers_gone(tmp_path):
    sim = _stepped(_sim(tmp_path), 2500)
    try:
        assert sim._customer_seq > 8, "no new customers minted"
        assert "c9" in sim.flow or sim._customer_seq >= 9
        assert len(sim.flow) <= 18  # bounded by seats, not a leak
        assert len(sim.scenario.npcs) == 7 + len(sim.flow)
    finally:
        sim.close()


def test_unknown_person_rejected(tmp_path):
    sim = _sim(tmp_path)
    try:
        with pytest.raises(KeyError):
            sim.talk("ghost", "hi")
    finally:
        sim.close()


def test_speech_routes_by_addressee():
    said, replied = [], []
    provider = RestaurantProvider(
        inner=_FakeInner(), on_speech=lambda n, s: said.append((n, s)),
        on_reply=lambda n, s: replied.append((n, s)))
    tick = "npc=auguste\nkind=tick\nspeaker=\ntext=[lang:english] hello"
    assert json.loads(provider.complete(tick))["speech"].startswith("Fake")
    assert said and not replied
    direct = ("npc=auguste\nkind=direct_message\nspeaker=you\n"
              "text=[lang:french] bonsoir")
    provider.complete(direct)
    assert replied and replied[-1][0] == "auguste"
    assert provider.live is True


def test_completion_without_llm_raises():
    provider = RestaurantProvider()
    assert provider.live is False
    with pytest.raises(LLMNotConfigured):
        provider.complete("npc=x\nkind=tick\nspeaker=\ntext=hi")


def test_boot_requires_llm(monkeypatch):
    for var in ("NPC_CORTEX_API_KEY", "NPC_LLM_API_KEY",
                "NPC_CORTEX_ENDPOINT", "NPC_CORTEX_MODEL",
                "NPC_CORTEX_FAKE_LLM"):
        monkeypatch.delenv(var, raising=False)
    assert key_status()["live"] is False
    with pytest.raises(LLMNotConfigured):
        build_provider()
    monkeypatch.setenv("NPC_CORTEX_FAKE_LLM", "1")
    assert key_status()["live"] is True
    assert build_provider().live is True


def test_build_provider_routes_by_endpoint_shape(monkeypatch):
    from npc_cortex.providers import ChatCompletionsProvider, HttpProvider
    monkeypatch.delenv("NPC_CORTEX_FAKE_LLM", raising=False)
    monkeypatch.setenv("NPC_CORTEX_API_KEY", "k")
    monkeypatch.setenv("NPC_CORTEX_MODEL", "muse-wonder-1.0")
    monkeypatch.setenv("NPC_CORTEX_ENDPOINT",
                       "https://api.meta.ai/v1/chat/completions")
    assert isinstance(build_provider().inner, ChatCompletionsProvider)
    monkeypatch.setenv("NPC_CORTEX_ENDPOINT", "https://llm.local/complete")
    assert isinstance(build_provider().inner, HttpProvider)


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("NPC_CORTEX_FAKE_LLM", "1")  # no endpoint in tests
    game = Game(out_dir=tmp_path / "out").start()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    httpd.game = game
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    try:
        yield base
    finally:
        game.stop()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(base, path):
    with _OPENER.open(base + path, timeout=5) as resp:
        return resp.status, resp.read()


def _post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_server_serves_ui_and_state(live):
    status, body = _get(live, "/")
    assert status == 200 and b"Maison Cinq" in body
    for name, marker in (("style.css", b"--brass"), ("game.js", b"/api/state")):
        status, body = _get(live, "/static/" + name)
        assert status == 200 and marker in body
    status, body = _get(live, "/api/state")
    state = json.loads(body)
    assert state["entities"] and state["tables"] and state["menu"] == [d["dish"] for d in MENU]
    assert set(state["key"]) >= {"live", "show"}


def test_server_talk_act_mode_role_lang(live):
    status, _ = _post(live, "/api/talk", {"to": "auguste", "text": "bonsoir"})
    assert status == 200
    status, body = _post(live, "/api/act", {"action": "order_dish",
                                            "params": {"dish": "Ratatouille"}})
    assert status == 200
    status, body = _post(live, "/api/role", {"role": "chef"})
    assert body["role"] == "chef"
    status, body = _post(live, "/api/lang", {"lang": "french"})
    assert body["lang"] == "french"
    status, _ = _post(live, "/api/mode", {"mode": "passive"})
    assert status == 200
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(live, "/api/talk", {"to": "auguste", "text": "hi"})
    assert exc.value.code == 403  # watching only
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(live, "/api/role", {"role": "pirate"})
    assert exc.value.code == 400


def test_talk_records_player_line_in_multilogue(tmp_path):
    sim = _sim(tmp_path)
    try:
        sim.talk("auguste", "The risotto smells divine!")
        tail = sim.state()["transcript"]
        mine = [t for t in tail if t["text"] == "The risotto smells divine!"]
        assert mine and mine[-1]["by"] == "you"
        heard = mine[-1]["heard_by"]
        assert "you" not in heard  # speaker excluded
        me = sim.entities["you"]
        expected = {eid for eid, e in sim.entities.items()
                    if eid != "you"
                    and ((e["x"] - me["x"]) ** 2 + (e["y"] - me["y"]) ** 2) ** 0.5 <= 12.0}
        assert set(heard) == expected  # proximity hearers, no more no less
    finally:
        sim.close()


def test_mint_customer_survives_warm_cache(tmp_path):
    out = tmp_path / "out"
    first = _sim(tmp_path)
    first._out_dir = out
    try:
        first._mint_customer()  # c9, cold cache
        assert "c9" in first.specs
    finally:
        first.close()
    second = Sim(RestaurantProvider(inner=_FakeInner()), out_dir=out)
    try:
        second._mint_customer()  # c9 again, warm cache: must not KeyError
        assert "c9" in second.specs
    finally:
        second.close()


def test_chat_thread_names_stranger_after_intro(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        assert sim.chats["c1"]["known"] is False  # guests start strangers
        assert sim.chats["nina"]["known"] is True  # staff are known crew
        sim.talk("c1", "hello there")
        assert sim.chats["c1"]["messages"][0]["by"] == "you"
        assert (tmp_path / "out" / "chat.json").is_file()  # record kept
        for _ in range(200):  # replies resolve on worker threads
            tm.step()
            if any(m["by"] == "c1" for m in sim.chats["c1"]["messages"]):
                break
            time.sleep(0.01)
        assert sim.chats["c1"]["known"] is True  # introduced by reply
        threads = sim.state()["chats"]
        assert threads["c1"]["name"] == sim.entities["c1"]["name"]
        assert threads["c1"]["known"] is True
    finally:
        sim.close()


def test_parties_seat_only_where_they_fit(tmp_path):
    sim = _sim(tmp_path)
    try:
        pid = sim._mint_party(kind="family")
        party = sim.parties[pid]
        assert 3 <= len(party["members"]) <= 4
        surnames = {sim.entities[c]["name"].split(" ")[-1]
                    for c in party["members"]}
        assert len(surnames) == 1  # one family, one name
        party["state"] = "waiting"
        table_id = sim._free_table_for(party)
        assert table_id is not None
        assert sim.tables[table_id]["seats"] >= len(party["members"])
        sim._seat(pid, table_id)
        table = sim.tables[table_id]
        assert table["guests"] == party["members"]
        assert table["guest"] == party["members"][0]  # compat marker
        assert all(sim.flow[c]["state"] == "walking" for c in party["members"])
    finally:
        sim.close()


def test_service_discussion_meal_and_bill_take_time(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim._seat("p1", "t1")  # solo guest, smallest table
        seated_at = ordered_at = eating_at = settled_at = None
        for _ in range(6000):
            tm.step()
            state = sim.parties["p1"]["state"] \
                if "p1" in sim.parties else "gone"
            if state == "seated" and seated_at is None:
                seated_at = sim.tick_count
            elif state == "ordered" and ordered_at is None:
                ordered_at = sim.tick_count
            elif state == "eating" and eating_at is None:
                eating_at = sim.tick_count
            elif state == "gone":
                settled_at = sim.tick_count
                break
        assert seated_at is not None and ordered_at is not None
        # greet + choice + confirm turns, each its own window
        assert ordered_at - seated_at >= 2 * DISCUSS_GAP, \
            (seated_at, ordered_at)
        assert eating_at is not None and settled_at is not None
        assert settled_at - eating_at >= EAT_TICKS + PAY_TICKS, \
            (eating_at, settled_at)
        assert sim.stats["served"] >= 1
    finally:
        sim.close()


def test_chatted_guest_lingers_instead_of_leaving(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim.talk("c1", "don't go, tell me about the risotto")
        sim._seat("p1", "t1")
        party = sim.parties["p1"]
        party["table"] = "t1"
        sim._set_party_state(party, "paying")
        party["timer"] = 2
        for _ in range(200):
            tm.step()
            if sim.parties.get("p1", {}).get("state") == "lingering":
                break
        assert sim.parties.get("p1", {}).get("state") == "lingering"
        assert sim.tables["t1"]["guest"] is None  # table freed anyway
        assert "c1" in sim.flow  # but the guest stays for the talk
        # conversation over: backdate the pin, they say bye and leave
        for msg in sim.chats["c1"]["messages"]:
            if msg["by"] == "you":
                msg["tick"] -= 100000
        for _ in range(500):
            tm.step()
            if "p1" not in sim.parties:
                break
        assert "p1" not in sim.parties  # pin expired: gone for good
    finally:
        sim.close()


def test_chatted_guest_never_storms_out(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim.talk("c1", "hang on, I'm coming over")
        for table in sim.tables.values():
            table["guest"] = "nobody"  # full house, the line festers
        sim.parties["p1"]["state"] = "waiting"
        sim.parties["p1"]["patience"] = 2
        _breathe(tm, 120)
        assert "p1" in sim.parties  # pinned: still here
        assert sim.stats["lost"] == 0
        assert sim.parties["p1"]["state"] == "waiting"
    finally:
        sim.close()


def test_arrivals_capped_by_free_table_seats(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        for table in sim.tables.values():
            table["guest"] = "nobody"  # no free seats anywhere
        _breathe(tm, 300)
        assert all(p["state"] == "away" for p in sim.parties.values()), \
            "parties entered a full house"
        assert len(sim.flow) == 8  # nobody new minted either
        for tid in ("t3", "t4"):  # free 8 seats for the 8 inside
            sim.tables[tid].update(guest=None, guests=[], party=None)
        for _ in range(300):
            tm.step()
            if any(p["state"] != "away" for p in sim.parties.values()):
                break
        assert any(p["state"] != "away" for p in sim.parties.values()), \
            "nobody entered once seats freed"
    finally:
        sim.close()


class _FakeInner:
    """Scripted stand-in for the live LLM endpoint."""

    def __init__(self, speech=None):
        self.prompts = []
        self.speech = speech
        self.calls = 0

    def complete(self, prompt):
        self.prompts.append(prompt)
        self.calls += 1
        line = self.speech if self.speech is not None \
            else "Fake line %d" % self.calls
        return json.dumps({"speech": line, "emotion": None,
                           "actions": [], "memory": []})


def _breathe(tm, steps, every=10):
    for i in range(steps):
        tm.step()
        if i % every == 0:
            time.sleep(0.005)


def test_live_prompt_reads_full_context(tmp_path):
    inner = _FakeInner(speech="Indeed, mes amis.")
    sim = Sim(RestaurantProvider(inner=inner), out_dir=tmp_path / "out")
    try:
        assert sim.chats["nina"]["known"] is True
        # NOTE: no talk() here — its worker would race this direct call.
        sim.chats["nina"]["messages"].append(
            {"by": "you", "text": "hello Nina, what do you recommend?",
             "tick": 0})
        sim.specs["nina"].long_memory.append(
            {"fact": "MARKER served the noisy anniversary table."})
        from collections import deque as _dq
        sim._heard["nina"] = _dq([{"by": "omar", "text": "MARKER pass is clear",
                                   "tick": 0}], maxlen=6)
        prompt = ("npc=nina\nkind=direct_message\nspeaker=you\n"
                  "text=[lang:english] hello\nmemory=[]")
        out = json.loads(sim.runtime.provider.complete(prompt))
        assert out["speech"] == "Indeed, mes amis."
        text = inner.prompts[-1]
        assert "Nina" in text  # persona adopted
        assert "Table service" in text  # contract skills read
        assert sim.specs["nina"].title("modern") in text
        assert "hello Nina, what do you recommend?" in text  # chats read
        assert "MARKER served the noisy" in text  # long memory read
        assert "MARKER pass is clear" in text  # overheard read
        assert "t3" in text or "table" in text  # surroundings read
    finally:
        sim.close()


def test_npcs_listen_to_room_speech(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        _breathe(tm, 150)
        heard = [h for h in sim._heard.get("c1", []) if h["by"] == "theo"]
        assert heard, "guest c1 overheard nothing from the host"
    finally:
        sim.close()


def test_named_hearer_answers_when_addressed(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        nina = sim.entities["nina"]
        sim.entities["you"].update(x=nina["x"], y=nina["y"],
                                   tx=nina["x"], ty=nina["y"])
        sim.talk("auguste", "Nina is wonderful tonight")
        start = sim.tick_count
        for _ in range(300):
            tm.step()
            time.sleep(0.005)
            if any(t["by"] == "nina" and t["tick"] > start
                   for t in sim.transcript):
                break
        assert any(t["by"] == "nina" and t["tick"] > start
                   for t in sim.transcript), "named hearer stayed silent"
    finally:
        sim.close()


def test_host_welcomes_arrivals(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        _breathe(tm, 150)
        welcomes = [t for t in sim.transcript if t["by"] == "theo"]
        assert len(welcomes) >= 3, [t["text"] for t in welcomes]
    finally:
        sim.close()


def test_long_wait_draws_complaints(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        for table in sim.tables.values():
            table["guest"] = "nobody"  # full house, the line festers
        sim.parties["p1"]["state"] = "waiting"
        sim.parties["p1"]["waited"] = 500
        sim.parties["p1"]["patience"] = 900
        start = sim.tick_count
        _breathe(tm, 250)
        assert sim.parties["p1"].get("complained_at") is not None
        assert any(t["by"] == "c1" and t["tick"] > start
                   for t in sim.transcript), "waiting guest never spoke up"
    finally:
        sim.close()


def test_waiter_checks_back_mid_meal(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        sim._seat("p1", "t1")
        party = sim.parties["p1"]
        party["table"] = "t1"
        sim._set_party_state(party, "eating")
        party["timer"] = 100
        start = sim.tick_count
        saw_checked = False
        for i in range(400):  # manual breathe: p1 may settle + leave
            tm.step()
            if i % 10 == 0:
                time.sleep(0.005)
            if sim.parties.get("p1", {}).get("checked"):
                saw_checked = True
        assert saw_checked, "checkin motive never fired"
        staff_said = any(t["by"] in ("nina", "omar") and t["tick"] > start
                         for t in sim.transcript)
        guest_said = any(t["by"] == "c1" and t["tick"] > start
                         for t in sim.transcript)
        assert staff_said, "no waiter checked back"
        assert guest_said, "guest never answered the checkin"
    finally:
        sim.close()


def test_idle_player_gets_addressed(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        priya = sim.entities["priya"]
        sim.entities["you"].update(x=priya["x"], y=priya["y"],
                                   tx=priya["x"], ty=priya["y"])
        _breathe(tm, 500)
        assert "priya" in sim.state()["chats"], "nobody addressed the player"
        thread = sim.chats["priya"]
        assert any(m["by"] == "priya" for m in thread["messages"])
    finally:
        sim.close()


def test_npcs_update_continuously(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        _breathe(tm, 700)
        short = sim.specs["nina"].short_memory
        assert any("overheard" in e.get("tags", []) for e in short), short
        disk = (tmp_path / "out" / "rush" / "nina"
                / "short-memory.json").read_text(encoding="utf-8")
        assert "overheard" in disk  # artifacts persist the night
        for _ in range(1300):
            tm.step()
            if sim.stats["served"] >= 1:
                break
        assert sim.stats["served"] >= 1
        facts = " ".join(
            f.get("fact", "") for wid in ("nina", "omar")
            for f in sim.specs[wid].long_memory)
        assert "Served" in facts and "table" in facts, facts[-300:]
    finally:
        sim.close()


def test_ignored_party_storms_out_and_leaves_for_good(tmp_path):
    sim = _sim(tmp_path)
    tm = make_task_manager()
    sim.attach(tm)
    try:
        for table in sim.tables.values():
            table["guest"] = "nobody"  # full house, no seating
        sim.parties["p1"]["state"] = "waiting"
        sim.parties["p1"]["patience"] = 2
        for _ in range(500):
            tm.step()
            if "p1" not in sim.parties:
                break
        assert "p1" not in sim.parties  # stormed out, gone for good
        assert sim.stats["lost"] == 1
        assert "c1" not in sim.flow
        assert all(n.id != "c1" for n in sim.scenario.npcs)
    finally:
        sim.close()
