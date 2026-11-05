# npc-cortex in brief

npc-cortex gives game NPCs a language-model brain without stalling
the frame loop. A Python runtime plans what each NPC says and does;
engines apply the results on their own timeline through one pump per
frame, while all model calls run on background threads with timeouts
and retries. Perception, implication gating for untrusted output,
engagements, environment awareness, mutual NPC knowledge with
long-term memories, and a full audit trail are built in.

A cast generator called the forge turns two TOML contracts — one
game description plus one file per quest — into complete NPCs with
personalities, setting-true names, stories, skills, memories, and
per-type playbooks. A clarity gate refuses ambiguous contracts
before anything is generated, and every scenario receives tiered
model, latency, and cost advice.

One integration per engine shares the same per-frame flow: sync
transforms, submit events, pump, then poll actions and dialogue with
cursors. Python engines (Panda3D, pygame, Godot, asyncio, plain
loops) attach in-process; Unity, Unreal, Godot, Rust, and Bevy
connect over HTTP through native clients. End-user API keys are
protected: never logged, header-only, with redacted display.

The repo ships a playable demo, Maison Cinq — a five-star
restaurant simulation with LLM-driven staff and customers in the
browser — plus a pinned Docker smoke suite covering every engine
and four agent skills that turn client and generation contracts
into reusable, self-evaluating checklists.
