# Maison Cinq — 5-star restaurant game

Demand-supply 2D game driven by Panda3D tasks and npc-cortex NPCs,
played in a web browser.

## Run

From the repo root:

```sh
export NPC_CORTEX_API_KEY=... NPC_CORTEX_ENDPOINT=... NPC_CORTEX_MODEL=...
python3 games/restaurant/server.py --port 8901
```

then open **http://127.0.0.1:8901** in a browser.

Every line is a live model completion — there are no scripted
fallbacks, and the server refuses to boot without a key.
(`NPC_CORTEX_FAKE_LLM=1` selects the test-only echo stand-in used by
the suite and smoke tests.)

Chats and the night's memories persist under `games/restaurant/out/`
across restarts. For a fresh night, stop the server and remove it:

```sh
rm -rf games/restaurant/out games/restaurant/out-smoke
```

## Play

- **Active mode**: pick any role (customer, waiter, chef, manager),
  click a person on the floor to open a **Chat** with them, talk in
  English/Français/Español/العربية, and use your role's actions
  (order, serve, cook, comp, …).
- Guests start as **strangers**: talk to someone and they introduce
  themselves, and the chat window takes their name. Every discussion
  is kept as a per-person record (persisted to `out/chat.json`).
  Guests you are talking to never quit mid-conversation: they linger
  at the bar after paying and leave only once the talk goes quiet.
- The house admits at most as many guests as there are seats at
  free tables — when full, arrivals wait outside for the door.
- Individuals, couples, families, and groups of friends arrive,
  are seated where they fit, and waiters walk over for a real
  ordering discussion — all at a humane pace, every step visible.
- **Passive mode**: sit back and watch the dinner rush run itself.
- Tonight's goal: seat the rush, feed every table, keep 5 stars.
  A critic dines anonymously.

## Under the hood

- `forge/` — game + quest TOMLs: 7 defined staff, 8 flow customers,
  tables/kitchen/bar/cellar/office places, 4 languages, fixed skill
  sets per type, and a `[communication]` contract (listening,
  addressing, initiative, memory). Quest 1 is the playable rush;
  quest 2 (`The Critic's Last Seating`) is a second validated
  scenario for the forge. Generated once at startup through the
  clarity gate (both score 100/100).
- `sim.py` — Panda3D `TaskManager` loop (headless): party flow
  (away → waiting → seated → ordering discussion → eating → paying
  → leaving), 2-slot kitchen with pass waits, patience, tips,
  rating, plus npc-cortex dialogue, memory, and action handlers.
- `provider.py` — live LLM via `NPC_CORTEX_API_KEY` +
  `NPC_CORTEX_ENDPOINT` + `NPC_CORTEX_MODEL`, prompted with skills,
  persona, history, short/long memories, overheard lines,
  surroundings, place knowledge, and chats — else a stage-aware
  polyglot composer with per-speaker and room-level anti-repeat
  memory. The header shows which is active.
- NPCs listen continuously, answer when named, and initiate:
  the host welcomes arrivals, waiters check back mid-meal, long
  waits draw complaints, and anyone near an idle player may speak
  up. Staff fold the night into their memories and artifacts.
- `server.py` + `static/` — stdlib HTTP server and the canvas UI
  (`index.html`, `style.css`, `game.js`).

## Smoke

```sh
python3 games/restaurant/smoke_play.py   # scripted HTTP playthrough
pytest tests/games/                      # sim + server tests
```
