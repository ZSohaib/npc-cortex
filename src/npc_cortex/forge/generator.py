"""The NPC generator: TOML contracts -> finished NPCs + artifacts.

Pipeline per quest::

    rubric gate -> fill fixed -> fill open (template, or LLM when a
    provider is given) -> validate spec -> write artifacts ->
    render skill-<npc-type>.md

``provider`` is any object with ``complete(prompt: str) -> str`` (the
same shape the runtime uses). Without one, open fields get deterministic
seeded template text, so the whole pipeline runs offline and stays
testable; ``provenance`` records ``fixed`` | ``template`` | ``llm`` per
field so nobody mistakes filler text for authored canon.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from .names import pick_name
from .profiles import PROFILES, profile_title
from .rubric import UnclearContract, evaluate
from .schemas import COVERED_FIELDS
from .skill import check_actions, render_skill_file
from .spec import INTELLECT_LABELS, NPCSpec

__all__ = ["NPCGenerator", "GenerationReport", "prompt_context"]


class GenerationReport:
    """What one ``run()`` produced."""

    def __init__(self) -> None:
        self.npcs: list = []          # NPCSpec, generation order
        self.skill_files: dict = {}   # npc_type -> path
        self.rubrics: dict = {}       # quest id -> RubricReport
        self.skipped: list = []       # npc ids reused from cache
        self.warnings: list = []

    def by_id(self, npc_id: str):
        for spec in self.npcs:
            if spec.id == npc_id:
                return spec
        raise KeyError(npc_id)


class NPCGenerator:
    def __init__(self, game, quests, provider=None, seed=None, registry=None) -> None:
        self.game = game
        self.quests = list(quests)
        self.provider = provider
        self.seed = game.seed if seed is None else int(seed)
        self.registry = registry  # optional ActionRegistry for skill-file checks

    # -- public ---------------------------------------------------------

    def run(self, out_dir, refresh: bool = False) -> GenerationReport:
        """Generate every quest's cast into ``out_dir``. Raises
        :class:`UnclearContract` when any quest fails the clarity gate."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        report = GenerationReport()
        manifest = self._read_manifest(out)
        for quest in self.quests:
            rubric = evaluate(self.game, quest)
            report.rubrics[quest.id] = rubric
            rubric.raise_unless_passed()
            for qnpc in quest.npcs:
                key = "%s/%s" % (quest.id, qnpc.id)
                fingerprint = self._fingerprint(quest, qnpc)
                if (not refresh and manifest.get(key) == fingerprint
                        and (out / quest.id / qnpc.id / "story.md").exists()):
                    report.skipped.append(key)
                    continue
                spec = self._generate(quest, qnpc)
                spec.write_artifacts(out / quest.id)
                manifest[key] = fingerprint
                report.npcs.append(spec)
        self._write_manifest(out, manifest)
        self._render_skills(out, report)
        return report

    # -- generation -----------------------------------------------------

    def _fingerprint(self, quest, qnpc) -> str:
        gtype = self.game.types[qnpc.type]
        payload = json.dumps({
            "seed": self.seed, "game": self.game.title,
            "setting": self.game.setting, "quest": quest.raw,
            "type": {"fixed": gtype.fixed, "open": gtype.open},
            "npc": {"fixed": qnpc.fixed, "open": qnpc.open, "mode": qnpc.mode},
            "provider": "llm" if self.provider is not None else "template",
        }, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _generate(self, quest, qnpc) -> NPCSpec:
        gtype = self.game.types[qnpc.type]
        fixed = dict(gtype.fixed)
        fixed.update(qnpc.fixed)
        opened = (set(gtype.open) | set(qnpc.open)) - set(fixed)
        rng = random.Random("%s/%s/%s" % (self.seed, quest.id, qnpc.id))
        context = {"quest": quest.id, "time": quest.time,
                   "location": fixed.get("location", ""),
                   "scenario": quest.scenario}
        values, provenance = {"id": qnpc.id, "npc_type": qnpc.type}, {}
        for key in COVERED_FIELDS:
            if key in fixed:
                values[key], provenance[key] = self._coerce(key, fixed[key]), "fixed"
        llm_values = self._llm_fill(quest, qnpc, sorted(opened), values, context)
        for key in sorted(opened):
            if key in llm_values:
                values[key], provenance[key] = llm_values[key], "llm"
            else:
                values[key], provenance[key] = self._template(
                    key, values, context, rng), "template"
        if "localization" not in values:
            values["localization"], provenance["localization"] = 1, "fixed"
        spec = NPCSpec(**{k: values[k] for k in
                          ("id", "npc_type") + COVERED_FIELDS
                          if k in values},
                       provenance=provenance, context=context)
        spec.awareness = self._awareness(spec)
        spec.validate()
        return spec

    def _awareness(self, spec) -> dict:
        """Familiarity + known facts per place (see ``places.py``)."""
        from ..places import familiarity, knowledge

        home = self.game.resolve_location(spec.location)
        out = {}
        for pid, place in self.game.places.items():
            score = familiarity(home, spec.localization, spec.intellect,
                                place.coords)
            out[pid] = {"familiarity": score,
                        "facts": knowledge(place, score,
                                           is_owner=(place.owner == spec.id))}
        return out

    @staticmethod
    def _coerce(key, value):
        if key == "body" and isinstance(value, str):
            return {"state": value, "detail": ""}
        if key == "body" and isinstance(value, dict):
            return {"state": value.get("state", "healthy"),
                    "detail": str(value.get("detail", ""))}
        if key in ("short_memory", "long_memory"):
            return list(value or [])
        if key == "skills":
            return [{"name": s["name"], "description": str(s.get("description", ""))}
                    for s in value]
        if key == "languages":
            return [str(x) for x in value]
        if key == "localization_range":
            return float(value)
        if key in ("age", "intellect", "wealth", "social_rank", "power", "health"):
            return int(value)
        return value

    # -- template filler (seeded, offline) --------------------------------

    def _template(self, key, values, context, rng):
        setting = self.game.setting
        profile = str(values.get("profile", "P11")).upper()
        title = profile_title(profile, setting)
        name = values.get("name") or pick_name(setting, values.get("gender", "any"), rng)
        location = values.get("location", "")
        loc_desc = self.game.locations.get(location, {}).get("description", location)
        time, scenario = context["time"], context["scenario"]
        if key == "name":
            return pick_name(setting, values.get("gender", "any"), rng)
        if key == "age":
            return rng.randint(18, 70)
        if key == "gender":
            return rng.choice(["female", "male"])
        if key == "profile":
            return rng.choice(sorted(PROFILES))
        if key == "intellect":
            return rng.randint(2, 4)
        if key == "languages":
            return [self.game.languages[0]]
        if key == "localization":
            return 1
        if key == "localization_range":
            if values.get("localization", 1) == 0:
                return round(rng.uniform(2, 12), 1)
            return 0.0
        if key == "body":
            return {"state": "healthy", "detail": ""}
        if key in ("wealth", "social_rank", "power"):
            return rng.randint(20, 80)
        if key == "health":
            return rng.randint(60, 100)
        if key == "story":
            return ("# %s\n\n%s is a %s of %s. %s\n\nDuring %s, %s finds "
                    "themselves bound to the events of %s: %s\n"
                    % (name, name, title.lower(), loc_desc or location,
                       "Known for: %s." % PROFILES[profile][2],
                       time, name.split()[0], location,
                       scenario[:240].strip()))
        if key == "skills":
            return [{"name": title + " craft",
                     "description": "The everyday trade %s plies in %s."
                                    % (name.split()[0], location)},
                    {"name": "Local lore",
                     "description": "Knows %s: %s" % (location, loc_desc or "home ground")}]
        if key == "short_memory":
            return [{"text": "Arrived in %s for %s." % (location, time), "tags": ["arrival"]}]
        if key == "long_memory":
            return [{"fact": "%s has lived in %s for years." % (name.split()[0], location),
                     "tags": ["roots"]}]
        raise AssertionError("no template for %r" % key)  # pragma: no cover

    # -- LLM filler ---------------------------------------------------------

    def _llm_fill(self, quest, qnpc, opened, values, context) -> dict:
        if self.provider is None or not opened:
            return {}
        wanted = [k for k in opened if k in
                  ("name", "age", "gender", "profile", "intellect", "languages",
                   "localization_range", "body", "wealth", "social_rank",
                   "power", "health", "story", "skills", "short_memory", "long_memory")]
        if not wanted:
            return {}
        prompt = (
            "Generate NPC fields as ONE JSON object with exactly these keys: %s.\n"
            "Types: name str, age int>=0, gender str, profile one of %s, intellect 1..5, "
            "languages list of str from %s, localization_range number>=0, "
            "body {state: healthy|handicapped, detail: str}, wealth/social_rank/power/health int 0..100, "
            "story markdown str, skills [{name, description}], "
            "short_memory [{text, tags}], long_memory [{fact, tags}].\n"
            "Game: %s (setting %s). Time: %s. Location: %s (%s). Scenario: %s\n"
            "NPC id %s of type %s (%s). Already fixed: %s. JSON only, no prose."
            % (", ".join(wanted), "/".join(sorted(PROFILES)), self.game.languages,
               self.game.title, self.game.setting, context["time"],
               context["location"],
               self.game.locations.get(context["location"], {}).get("description", ""),
               context["scenario"][:600], qnpc.id, qnpc.type,
               self.game.types[qnpc.type].description,
               json.dumps({k: values.get(k) for k in sorted(values)}, default=str)))
        try:
            raw = self.provider.complete(prompt)
            data = json.loads(raw) if isinstance(raw, str) else {}
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for key in wanted:
            if key not in data:
                continue
            try:
                out[key] = self._coerce(key, data[key])
                _check_value(key, out[key], self.game)
            except Exception:
                out.pop(key, None)  # invalid LLM value -> template fallback
        return out

    # -- skills + manifest ----------------------------------------------------

    def _render_skills(self, out, report) -> None:
        by_type: dict = {}
        for spec in report.npcs:
            by_type.setdefault(spec.npc_type, []).append(spec)
        for npc_type, specs in by_type.items():
            known, unknown = ([], [])
            if self.registry is not None:
                known, unknown = check_actions(self.game.types[npc_type].actions,
                                               self.registry)
                if unknown:
                    report.warnings.append(
                        "type %r lists unknown actions: %s" % (npc_type, unknown))
            path = out / ("skill-%s.md" % npc_type)
            path.write_text(render_skill_file(
                npc_type, self.game, specs,
                quest_ids=sorted({s.context.get("quest", "?") for s in specs}),
                known_actions=known, unknown_actions=unknown),
                encoding="utf-8")
            report.skill_files[npc_type] = str(path)

    @staticmethod
    def _read_manifest(out) -> dict:
        try:
            return json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_manifest(out, manifest) -> None:
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                           encoding="utf-8")


def _surroundings_block(spec, limit: int = 6) -> str:
    """Known places, deepest familiarity first, for prompt context."""
    bits = []
    for pid, entry in spec.known_places()[:limit]:
        facts = entry.get("facts", {})
        bit = "%s (%s): %s" % (pid, facts.get("kind", "place"),
                               facts.get("description", ""))
        if facts.get("owner"):
            bit += " Owned by %s." % facts["owner"]
        if facts.get("interior"):
            bit += " Inside: %s" % facts["interior"]
        for text in facts.get("hidden", []):
            bit += " Hidden: %s" % text
        bits.append(bit)
    return "\n".join(bits)


def _check_value(key, value, game) -> None:
    """Validate one filled value the way the rubric validates fixed ones."""
    if key == "profile" and str(value).upper() not in PROFILES:
        raise ValueError("bad profile")
    if key == "intellect" and value not in (1, 2, 3, 4, 5):
        raise ValueError("bad intellect")
    if key == "languages" and (not value or any(x not in game.languages for x in value)):
        raise ValueError("bad languages")
    if key in ("wealth", "social_rank", "power", "health") and (
            not isinstance(value, int) or not 0 <= value <= 100):
        raise ValueError("bad stat")
    if key == "age" and (not isinstance(value, int) or value < 0):
        raise ValueError("bad age")
    if key in ("name", "gender", "story") and (
            not isinstance(value, str) or not value.strip()):
        raise ValueError("bad text")


def prompt_context(spec: NPCSpec, budget_chars: int = 2000) -> str:
    """Pack story/skills/memories into a bounded prompt block for providers.

    Oldest short-memory entries and trailing story text are cut first so
    the block fits ``budget_chars`` -- the latency/memory control for
    lore-heavy NPCs.
    """
    chunks = ["# %s (%s)" % (spec.name, spec.id),
              spec.story.strip(),
              "## Skills",
              "; ".join(s["name"] for s in spec.skills),
              "## Remembered",
              "; ".join(e.get("text", e.get("fact", "")) for e in
                        list(spec.long_memory) + list(spec.short_memory))]
    surroundings = _surroundings_block(spec)
    if surroundings:
        chunks += ["## Surroundings", surroundings]
    text = "\n".join(chunks)
    if len(text) <= budget_chars:
        return text
    keep = []
    for chunk in reversed(chunks):
        if sum(map(len, keep)) + len(chunk) + 1 <= budget_chars:
            keep.append(chunk)
        else:
            break
    keep.append(chunks[0])
    return "\n".join(reversed(keep))[:budget_chars]
