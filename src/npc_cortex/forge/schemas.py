"""TOML contracts: ``game-description.toml`` + ``game-quest-<n>.toml``.

The game developer describes the game once (structure, settings,
locations, languages, npc types) and each quest as a scenario with its
NPC cast. Every NPC field ends up either **fixed** (a value in the
TOMLs) or **open** (listed in ``open = [...]`` for the filler to
generate) -- the rubric in :mod:`npc_cortex.forge.rubric` refuses
anything in between. Requires Python 3.11+ (``tomllib``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..places import Place

__all__ = ["Game", "Quest", "QuestNPC", "ContractError", "load_game",
           "load_quest", "COVERED_FIELDS"]

try:
    import tomllib
except ImportError as exc:  # Python < 3.11
    raise ImportError(
        "npc_cortex.forge needs Python 3.11+ (tomllib) to read game TOMLs"
    ) from exc

#: Spec fields that must each be fixed or open (id/npc_type are structural).
COVERED_FIELDS = (
    "name", "age", "gender", "profile", "intellect", "languages",
    "location", "localization", "localization_range", "body", "wealth",
    "social_rank", "power", "health", "story", "skills",
    "short_memory", "long_memory",
)


class ContractError(Exception):
    """A game/quest TOML cannot even be read as a contract."""


@dataclass
class GameType:
    name: str
    fixed: dict = field(default_factory=dict)
    open: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    description: str = ""


@dataclass
class Game:
    title: str
    setting: str
    languages: list
    locations: dict          # name -> {"coords": tuple, "description": str}
    types: dict              # name -> GameType
    places: dict = field(default_factory=dict)  # name -> Place
    seed: int = 0
    default_horizon: float = 10.0
    default_implication: float = 0.5
    time_current: str = ""
    cost_tier: str = "medium"  # low | medium | high (advisor input)
    raw: dict = field(default_factory=dict)

    def resolve_location(self, name: str) -> tuple:
        try:
            return self.locations[str(name)]["coords"]
        except KeyError:
            raise ContractError("unknown location %r (game defines: %s)"
                                % (name, sorted(self.locations)))


@dataclass
class QuestNPC:
    id: str
    type: str
    mode: str = "generic"    # defined | generic (documentary; gate is fixed-vs-open)
    fixed: dict = field(default_factory=dict)
    open: list = field(default_factory=list)


@dataclass
class Quest:
    id: str
    title: str
    scenario: str
    time: str
    npcs: list = field(default_factory=list)  # list[QuestNPC]
    latency_budget_ms: int = 2000
    dialogue_intensity: str = "medium"  # low | medium | high (advisor input)
    raw: dict = field(default_factory=dict)


def _read_toml(path) -> dict:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ContractError("TOML file not found: %s" % path)
    except tomllib.TOMLDecodeError as exc:
        raise ContractError("invalid TOML in %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ContractError("top level of %s must be a TOML table" % path)
    return data


def load_game(path) -> Game:
    """Parse ``game-description.toml`` into a :class:`Game`."""
    data = _read_toml(path)
    game = data.get("game")
    if not isinstance(game, dict):
        raise ContractError("%s: missing [game] table" % path)
    for key in ("title", "setting"):
        if not game.get(key) or not isinstance(game[key], str):
            raise ContractError("%s: [game].%s must be a non-empty string"
                                % (path, key))
    languages = game.get("languages", [])
    if (not isinstance(languages, list) or not languages
            or not all(isinstance(x, str) and x for x in languages)):
        raise ContractError("%s: [game].languages must be a non-empty list"
                            % path)
    locations = {}
    for name, entry in (data.get("locations") or {}).items():
        if not isinstance(entry, dict):
            raise ContractError("%s: [locations.%s] must be a table" % (path, name))
        coords = entry.get("coords")
        if (not isinstance(coords, list) or len(coords) not in (2, 3)
                or not all(isinstance(c, (int, float)) for c in coords)):
            raise ContractError(
                "%s: [locations.%s].coords must be [x, y] or [x, y, z]"
                % (path, name))
        locations[name] = {"coords": tuple(float(c) for c in coords),
                           "description": str(entry.get("description", ""))}
    if not locations:
        raise ContractError("%s: define at least one [locations.<name>]" % path)
    types = {}
    for name, entry in (data.get("npc_types") or {}).items():
        if not isinstance(entry, dict):
            raise ContractError("%s: [npc_types.%s] must be a table" % (path, name))
        entry = dict(entry)
        types[name] = GameType(
            name=name,
            fixed={k: v for k, v in entry.items()
                   if k not in ("open", "actions", "description")},
            open=list(entry.get("open", []) or []),
            actions=list(entry.get("actions", []) or []),
            description=str(entry.get("description", "")),
        )
    if not types:
        raise ContractError("%s: define at least one [npc_types.<name>]" % path)
    places = {}
    for name, entry in (data.get("places") or {}).items():
        if not isinstance(entry, dict):
            raise ContractError("%s: [places.%s] must be a table" % (path, name))
        coords = entry.get("coords")
        if (not isinstance(coords, list) or len(coords) not in (2, 3)
                or not all(isinstance(c, (int, float)) for c in coords)):
            raise ContractError(
                "%s: [places.%s].coords must be [x, y] or [x, y, z]"
                % (path, name))
        hidden = entry.get("hidden", []) or []
        if not isinstance(hidden, list):
            raise ContractError("%s: [places.%s].hidden must be a list"
                                % (path, name))
        for i, item in enumerate(hidden):
            if not isinstance(item, dict) or not item.get("text"):
                raise ContractError(
                    "%s: [places.%s].hidden #%d needs {text, min_familiarity}"
                    % (path, name, i))
            try:
                level = int(item.get("min_familiarity", 100))
            except (TypeError, ValueError):
                raise ContractError(
                    "%s: [places.%s].hidden #%d min_familiarity must be 0..100"
                    % (path, name, i))
            if not 0 <= level <= 100:
                raise ContractError(
                    "%s: [places.%s].hidden #%d min_familiarity must be 0..100"
                    % (path, name, i))
        places[name] = Place.from_dict(name, entry)
    gen = data.get("generation") or {}
    time_table = data.get("time") or {}
    return Game(
        title=game["title"], setting=game["setting"], languages=list(languages),
        locations=locations, types=types, places=places,
        seed=int(gen.get("seed", 0)),
        default_horizon=float(game.get("default_horizon", 10.0)),
        default_implication=float(game.get("default_implication", 0.5)),
        time_current=str(time_table.get("current", "")),
        cost_tier=str(gen.get("cost_tier", "medium")), raw=data,
    )


def load_quest(path) -> Quest:
    """Parse ``game-quest-<n>.toml`` into a :class:`Quest`."""
    data = _read_toml(path)
    quest = data.get("quest")
    if not isinstance(quest, dict):
        raise ContractError("%s: missing [quest] table" % path)
    for key in ("id", "title", "scenario", "time"):
        if not quest.get(key) or not isinstance(quest[key], str):
            raise ContractError("%s: [quest].%s must be a non-empty string"
                                % (path, key))
    npcs = []
    entries = data.get("npc")
    if not isinstance(entries, list) or not entries:
        raise ContractError("%s: define at least one [[npc]]" % path)
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError("%s: [[npc]] #%d must be a table" % (path, i))
        entry = dict(entry)
        try:
            nid, ntype = entry.pop("id"), entry.pop("type")
        except KeyError:
            raise ContractError("%s: [[npc]] #%d needs 'id' and 'type'" % (path, i))
        if not nid or not ntype or not isinstance(nid, str) or not isinstance(ntype, str):
            raise ContractError("%s: [[npc]] #%d needs string 'id' and 'type'"
                                % (path, i))
        mode = str(entry.pop("mode", "generic"))
        if mode not in ("defined", "generic"):
            raise ContractError("%s: [[npc]] %r mode must be defined|generic"
                                % (path, nid))
        npcs.append(QuestNPC(id=nid, type=ntype, mode=mode,
                             fixed={k: v for k, v in entry.items() if k != "open"},
                             open=list(entry.get("open", []) or [])))
    return Quest(
        id=quest["id"], title=quest["title"], scenario=quest["scenario"],
        time=quest["time"], npcs=npcs,
        latency_budget_ms=int(quest.get("latency_budget_ms", 2000)),
        dialogue_intensity=str(quest.get("dialogue_intensity", "medium")),
        raw=data,
    )
