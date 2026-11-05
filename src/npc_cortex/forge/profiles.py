"""The 16 personality profiles.

Profiles are 4 binary axes, so every combination is a distinct, stable
profile id (``P00``..``P15``). Axes:

* Drive: ``bold`` | ``cautious``
* Heart: ``warm`` | ``aloof``
* Order: ``principled`` | ``free``
* Mind:  ``curious`` | ``steadfast``

Each profile has a neutral name plus a setting-appropriate title for the
supported settings (``medieval``, ``scifi``, ``modern``); unknown
settings fall back to the neutral name. Titles are what the generator
calls the personality in stories, ``skill-<npc-type>.md`` files, and
prompts -- never invent a 17th profile.
"""

from __future__ import annotations

__all__ = ["PROFILES", "SETTINGS", "profile", "profile_title"]

SETTINGS = ("medieval", "scifi", "modern")

# id -> (neutral name, axes, trait line, speech hint, {setting: title})
PROFILES = {
    "P00": ("Vanguard", ("bold", "warm", "principled", "curious"),
            "Charges first, for others first.",
            "direct, rousing, asks what others need",
            {"medieval": "Oathkeeper", "scifi": "Pathfinder", "modern": "Organizer"}),
    "P01": ("Warden", ("bold", "warm", "principled", "steadfast"),
            "Stands the line so others don't have to.",
            "plain, reassuring, repeats the plan",
            {"medieval": "Castellan", "scifi": "Shield Officer", "modern": "Guardian"}),
    "P02": ("Herald", ("bold", "warm", "free", "curious"),
            "Turns strangers into allies by sheer momentum.",
            "fast, vivid, name-drops new ideas",
            {"medieval": "Troubadour", "scifi": "First Contact", "modern": "Promoter"}),
    "P03": ("Hearth", ("bold", "warm", "free", "steadfast"),
            "Adopts every cause and every stray.",
            "loud, affectionate, feeds people first",
            {"medieval": "Innkeeper", "scifi": "Quartermaster", "modern": "Host"}),
    "P04": ("Inquisitor", ("bold", "aloof", "principled", "curious"),
            "Questions everything, forgives little.",
            "clipped, probing, cites rules",
            {"medieval": "Justiciar", "scifi": "Auditor", "modern": "Inspector"}),
    "P05": ("Sentinel", ("bold", "aloof", "principled", "steadfast"),
            "Duty is the whole personality.",
            "terse, formal, states orders",
            {"medieval": "Knight-Captain", "scifi": "Warrant Officer", "modern": "Sergeant"}),
    "P06": ("Maverick", ("bold", "aloof", "free", "curious"),
            "Breaks rules to test them.",
            "dry, challenging, loves edge cases",
            {"medieval": "Freeblade", "scifi": "Test Pilot", "modern": "Hacker"}),
    "P07": ("Recluse", ("bold", "aloof", "free", "steadfast"),
            "Acts alone and prefers it that way.",
            "few words, flat, ends conversations",
            {"medieval": "Hermit", "scifi": "Drifter", "modern": "Loner"}),
    "P08": ("Oracle", ("cautious", "warm", "principled", "curious"),
            "Warns gently and is usually right.",
            "soft, riddling, hedges with care",
            {"medieval": "Seer", "scifi": "Analyst", "modern": "Counselor"}),
    "P09": ("Confessor", ("cautious", "warm", "principled", "steadfast"),
            "Keeps every secret and every promise.",
            "slow, kind, never gossips",
            {"medieval": "Abbot", "scifi": "Chaplain", "modern": "Therapist"}),
    "P10": ("Jester", ("cautious", "warm", "free", "curious"),
            "Defuses danger with a joke.",
            "playful, quick, hides nerves in humor",
            {"medieval": "Fool", "scifi": "Morale Officer", "modern": "Comic"}),
    "P11": ("Keeper", ("cautious", "warm", "free", "steadfast"),
            "Remembers everyone's story but their own.",
            "gentle, nostalgic, offers tea",
            {"medieval": "Archivist", "scifi": "Librarian", "modern": "Nurse"}),
    "P12": ("Strategist", ("cautious", "aloof", "principled", "curious"),
            "Plans in decades, speaks in minutes.",
            "precise, conditional, numbers everything",
            {"medieval": "Spymaster", "scifi": "Tactician", "modern": "Planner"}),
    "P13": ("Monk", ("cautious", "aloof", "principled", "steadfast"),
            "Still water, deep vows.",
            "minimal, even, quotes doctrine",
            {"medieval": "Monk", "scifi": "Contemplative", "modern": "Ascetic"}),
    "P14": ("Trickster", ("cautious", "aloof", "free", "curious"),
            "Collects secrets and spends them.",
            "oblique, amused, answers sideways",
            {"medieval": "Cutpurse", "scifi": "Smuggler", "modern": "Con Artist"}),
    "P15": ("Ghost", ("cautious", "aloof", "free", "steadfast"),
            "Present everywhere, known nowhere.",
            "whispers, vanishes mid-sentence",
            {"medieval": "Wraith", "scifi": "Ghost", "modern": "Stranger"}),
}


def profile(pid: str) -> dict:
    """Return the profile record for ``P00``..``P15`` (raises ``KeyError``)."""
    pid = str(pid).upper()
    name, axes, trait, speech, titles = PROFILES[pid]
    return {"id": pid, "name": name, "axes": axes, "trait": trait,
            "speech": speech, "titles": dict(titles)}


def profile_title(pid: str, setting: str) -> str:
    """Setting-appropriate title for a profile (falls back to neutral)."""
    rec = profile(pid)
    return rec["titles"].get(str(setting).lower(), rec["name"])
