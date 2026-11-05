"""End-user API-key acquisition, kept protected.

Resolution order (first hit wins):

1. ``NPC_CORTEX_API_KEY`` environment variable (same key
   ``HttpProvider`` sends, header-only, never in a body).
   ``NPC_LLM_API_KEY`` is honoured as a pre-rename fallback.
2. ``~/.npc_cortex/key`` -- a file this module stores with ``0600``
   permissions; group/other readable files are refused.
3. Interactive prompt (``getpass``); the user may persist it via (2).

The key is never printed, never logged, and never embedded in prompts:
use :func:`fingerprint` (``...last4``) for display and :func:`redact`
before logging anything that might contain it.
"""

from __future__ import annotations

import getpass
import os
import stat
from pathlib import Path

__all__ = ["KEY_ENV", "LEGACY_KEY_ENV", "KeyVault", "acquire_key",
           "resolve_key", "store_key", "fingerprint", "redact",
           "default_key_file"]

KEY_ENV = "NPC_CORTEX_API_KEY"
LEGACY_KEY_ENV = "NPC_LLM_API_KEY"  # pre-rename fallback


def default_key_file() -> Path:
    return Path(os.path.expanduser("~")) / ".npc_cortex" / "key"


def fingerprint(key: str) -> str:
    """Display form of a key: ``...`` + last 4 chars (never the key)."""
    key = str(key or "")
    return "..." + key[-4:] if len(key) > 4 else "(empty)"


def redact(text: str, key) -> str:
    """Replace every occurrence of ``key`` in ``text`` with ``***``."""
    if not key:
        return text
    return str(text).replace(str(key), "***")


def store_key(key: str, path=None) -> Path:
    """Persist ``key`` with ``0600`` permissions; return the path."""
    path = Path(path) if path else default_key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open with O_CREAT|O_EXCL semantics avoided on purpose (rotation
    # rewrites); permissions are forced after the write instead.
    path.write_text(str(key).strip() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def resolve_key(env=None, key_file=None):
    """Return ``(key, source)`` or ``(None, None)``. ``source`` is
    ``"env"`` or ``"file"``. A file readable by group/other is refused
    (treated as missing) rather than trusted."""
    env = os.environ if env is None else env
    key = (env.get(KEY_ENV) or "").strip()
    if key:
        return key, "env"
    key = (env.get(LEGACY_KEY_ENV) or "").strip()
    if key:
        return key, "env (legacy)"
    path = Path(key_file) if key_file else default_key_file()
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None, None
    if mode & 0o077:
        return None, None  # unsafe permissions: refuse, don't warn-and-use
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    return (key, "file") if key else (None, None)


def acquire_key(prompt: str = "NPC LLM API key: ", store: bool = True,
                input_fn=None, key_file=None, env=None):
    """Guided acquisition for end-users. Returns ``(key, source)`` where
    ``source`` is ``"env"``, ``"file"``, or ``"prompt"``. With
    ``store=True`` a prompted key is persisted via :func:`store_key`.
    ``input_fn`` injects test input (defaults to ``getpass.getpass``)."""
    key, source = resolve_key(env=env, key_file=key_file)
    if key:
        return key, source
    ask = input_fn if input_fn is not None else getpass.getpass
    key = (ask(prompt) or "").strip()
    if not key:
        return None, None
    if store:
        store_key(key, key_file)
        return key, "prompt+stored"
    return key, "prompt"


class KeyVault:
    """One game's key holder: resolves once, redacts everywhere."""

    def __init__(self, env=None, key_file=None) -> None:
        self.key, self.source = resolve_key(env=env, key_file=key_file)

    def __bool__(self) -> bool:
        return bool(self.key)

    def auth_header(self) -> dict:
        """``{"Authorization": "Bearer <key>"}``; raises when empty."""
        if not self.key:
            raise RuntimeError("no API key: set %s or run acquire_key()"
                               % KEY_ENV)
        return {"Authorization": "Bearer " + self.key}

    def show(self) -> str:
        """Safe display form (``...last4`` + source)."""
        if not self.key:
            return "(no key)"
        return "%s (from %s)" % (fingerprint(self.key), self.source)

    def redact(self, text: str) -> str:
        """Scrub the key out of log/probe text."""
        return redact(text, self.key)
