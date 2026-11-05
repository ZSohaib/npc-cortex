"""Restaurant dialogue: live LLM only — no scripted lines.

Every spoken line is a real-time model completion. With
``NPC_CORTEX_API_KEY`` plus ``NPC_CORTEX_ENDPOINT``/``NPC_CORTEX_MODEL``
set, dialogue comes from the live model, prompted with the speaker's
persona, skills, scene, history, memories, surroundings, and chats.
Without them the game refuses to boot: ``LLMNotConfigured`` tells the
operator exactly what to set.

``NPC_CORTEX_FAKE_LLM=1`` selects a test-only echo stand-in (used by
the suite and smoke tests where no endpoint exists). It derives every
reply from the incoming prompt — there are no word banks anywhere.

Language rides in the event text as ``[lang:xx]`` (the runtime carries
event text verbatim into the prompt); this wrapper strips the tag and
instructs the model to answer in that language. Service stages ride as
``stage:<name>`` with ``table:<id>`` / ``dish:<name>`` context.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from npc_cortex.forge.keys import KeyVault  # noqa: E402
from npc_cortex.providers import ChatCompletionsProvider, HttpProvider  # noqa: E402

__all__ = ["RestaurantProvider", "build_provider", "key_status",
           "LLMNotConfigured", "LANGS"]

LANGS = ("english", "french", "spanish", "arabic")
LANG_RE = re.compile(r"\[lang:(\w+)\]")
STAGE_RE = re.compile(r"stage:([a-z_]+)")

SETUP_HINT = ("set NPC_CORTEX_API_KEY + NPC_CORTEX_ENDPOINT + "
              "NPC_CORTEX_MODEL for live LLM dialogue "
              "(or NPC_CORTEX_FAKE_LLM=1 for the test stand-in)")


class LLMNotConfigured(Exception):
    """No live model (and no test stand-in): the game cannot speak."""


class _EchoInner:
    """Test-only LLM stand-in: input-derived replies, zero word banks."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        scene = ""
        for line in (prompt or "").splitlines():
            if line.startswith("Scene:"):
                scene = line[len("Scene:"):].strip()
        speech = "Heard (#%d): %s" % (self.calls, scene[:90] or "go on")
        return json.dumps({"speech": speech, "emotion": None,
                           "actions": [], "memory": []})


def key_status():
    """``{"live": bool, "show": ..., "fake": bool}`` for the header."""
    if os.environ.get("NPC_CORTEX_FAKE_LLM", "") == "1":
        return {"live": True, "fake": True, "show": "test stand-in (fake)",
                "endpoint": None, "model": None, "hint": None}
    vault = KeyVault()
    endpoint = os.environ.get("NPC_CORTEX_ENDPOINT", "").strip()
    model = os.environ.get("NPC_CORTEX_MODEL", "").strip()
    live = bool(vault) and bool(endpoint) and bool(model)
    return {"live": live, "fake": False,
            "show": vault.show() if vault else "no key configured",
            "endpoint": endpoint or None, "model": model or None,
            "hint": None if live else SETUP_HINT}


def build_provider():
    """Live provider wrapped; raises when unconfigured.

    An endpoint naming ``chat/completions`` selects the OpenAI-compatible
    chat provider (Meta Model API et al.); anything else keeps the legacy
    ``{"model", "prompt"}`` HTTP provider.
    """
    status = key_status()
    if status["fake"]:
        return RestaurantProvider(inner=_EchoInner())
    if status["live"]:
        endpoint, model = status["endpoint"], status["model"]
        if "chat/completions" in endpoint:
            inner = ChatCompletionsProvider(endpoint, model)
        else:
            inner = HttpProvider(endpoint, model)
        return RestaurantProvider(inner=inner)
    raise LLMNotConfigured(SETUP_HINT)


class RestaurantProvider:
    def __init__(self, inner=None, on_speech=None, on_reply=None) -> None:
        self.inner = inner
        # on_speech(npc_id, speech): the runtime's gateway records the
        # *recipient*, so speaker attribution is captured here, where the
        # prompt still names the speaking NPC.
        self.on_speech = on_speech
        # on_reply(npc_id, speech): same, for lines addressed to the player.
        self.on_reply = on_reply
        # Sim hooks (set by Sim; guarded):
        # persona_fn(npc_id, speaker) -> full context;
        # recent_fn(n) -> [texts]; known_fn(npc_id) -> bool.
        self.persona_fn = None
        self.recent_fn = None
        self.known_fn = None

    @property
    def live(self) -> bool:
        return self.inner is not None

    @staticmethod
    def _parts(prompt):
        fields = {}
        for line in (prompt or "").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key.strip()] = value.strip()
        return fields

    def _persona(self, npc_id, speaker=None):
        if self.persona_fn is None:
            return {}
        try:
            return dict(self.persona_fn(npc_id, speaker) or {})
        except TypeError:  # legacy one-arg hook
            try:
                return dict(self.persona_fn(npc_id) or {})
            except Exception:
                return {}
        except Exception:
            return {}

    def _recent(self, n):
        if self.recent_fn is None:
            return []
        try:
            return list(self.recent_fn(n) or [])
        except Exception:
            return []

    def _known(self, npc_id):
        if self.known_fn is None:
            return True
        try:
            return bool(self.known_fn(npc_id))
        except Exception:
            return True

    def complete(self, prompt: str) -> str:
        if self.inner is None:
            raise LLMNotConfigured(SETUP_HINT)
        fields = self._parts(prompt or "")
        npc = fields.get("npc", "host")
        kind = fields.get("kind", "")
        speaker = fields.get("speaker", "")
        text = fields.get("text", "")
        lang = "english"
        match = LANG_RE.search(prompt or "")
        if match and match.group(1).lower() in LANGS:
            lang = match.group(1).lower()
        to_you = "to:you" in (text or "")
        persona = self._persona(npc, speaker or ("you" if to_you else None))
        speech = self._complete_live(fields, npc, kind, speaker, text,
                                     lang, persona)
        if ((kind == "direct_message" and speaker == "you") or to_you) \
                and self.on_reply is not None:
            self.on_reply(npc, speech)
        elif self.on_speech is not None:
            self.on_speech(npc, speech)
        return json.dumps({"speech": speech, "emotion": None,
                           "actions": [], "memory": []})

    @staticmethod
    def _section(title, items, cap=3, width=140):
        shown = ["- " + str(item)[:width] for item in (items or [])[:cap]]
        if not shown:
            return ""
        return title + ":\n" + "\n".join(shown) + "\n"

    def _complete_live(self, fields, npc, kind, speaker, text, lang,
                       persona):
        name = persona.get("first") or persona.get("name") or npc
        role = persona.get("role", "restaurant guest")
        profile = persona.get("profile", "")
        story = (persona.get("story") or "")[:220]
        recent = self._recent(6)
        scene = "Something happens around you; react briefly."
        if kind == "direct_message" and speaker == "you":
            scene = "The player says to you: %r. Answer them." % text
            if not self._known(npc):
                scene += (" You have never met the player: introduce "
                          "yourself by name (%s) first." % name)
        elif kind == "direct_message":
            scene = "%s says to you: %r. Answer them." % (speaker, text)
        elif "to:you" in (text or ""):
            scene = ("You chose to address the player. "
                     "Say what you need to say.")
        stage = STAGE_RE.search(text or "")
        if stage:
            scene += " Service moment: %s." % stage.group(1).replace("_", " ")
        who = speaker or ("the player" if "to:you" in (text or "") else "")
        prompt = (
            "You are %s, %s at Maison Cinq, a 5-star restaurant. "
            "Personality: %s. %s\n" % (name, role, profile, story)
            + self._section("Your skills", persona.get("skills"), 4)
            + self._section("What you know about this place",
                            persona.get("aware"), 2)
            + self._section("Around you right now",
                            (persona.get("near") or [])
                            + ["nearby: " + ", ".join(persona.get("actors")
                                                     or [])], 5)
            + self._section("Your long-term memories",
                            persona.get("long_memory"), 4)
            + self._section("Your short-term memories",
                            persona.get("short_memory"), 4)
            + self._section("You overheard",
                            persona.get("heard"), 3)
            + self._section("Your history with %s" % (who or "others"),
                            persona.get("history"), 3)
            + ("Your relationship with %s: %s.\n" % (
                who, persona.get("relation"))
               if persona.get("relation") else "")
            + self._section("Your chat with the player",
                            persona.get("chat"), 4)
            + self._section("The room just heard", recent, 6)
            + "Scene: %s\n"
            "Rules: stay in character as %s; one or two sentences; "
            "respond in %s; draw on your skills, memories, and what you "
            "know about this place and %s; never repeat a line the room "
            "just heard; address nobody by a name you were not given."
            % (scene, name, lang, who or "the room"))
        raw = self.inner.complete(prompt)
        try:
            speech = json.loads(raw).get("speech") or raw.strip()
        except Exception:
            speech = raw.strip()
        if not speech:
            raise ValueError("empty completion from LLM")
        return speech
