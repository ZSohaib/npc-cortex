"""Key tests: acquisition order, 0600 protection, never leak."""

import os
import stat

from npc_cortex.forge.keys import (KEY_ENV, LEGACY_KEY_ENV, KeyVault,
                                   acquire_key, fingerprint, redact,
                                   resolve_key, store_key)


def test_env_wins_over_file(tmp_path, monkeypatch):
    key_file = tmp_path / "key"
    store_key("file-key-45678", key_file)
    monkeypatch.setenv(KEY_ENV, "env-key-12345")
    key, source = resolve_key(env=dict(os.environ), key_file=key_file)
    assert (key, source) == ("env-key-12345", "env")


def test_legacy_env_var_still_honoured():
    key, source = resolve_key(env={LEGACY_KEY_ENV: "legacy-key-1"}, key_file="/nonexistent")
    assert (key, source) == ("legacy-key-1", "env (legacy)")
    key, source = resolve_key(env={KEY_ENV: "new-key-1", LEGACY_KEY_ENV: "legacy-key-1"})
    assert (key, source) == ("new-key-1", "env")


def test_file_is_used_and_stored_0600(tmp_path):
    key_file = tmp_path / "sub" / "key"
    store_key("file-key-45678", key_file)
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    key, source = resolve_key(env={}, key_file=key_file)
    assert (key, source) == ("file-key-45678", "file")


def test_unsafe_file_permissions_are_refused(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("leaky-key")
    os.chmod(key_file, 0o644)
    assert resolve_key(env={}, key_file=key_file) == (None, None)


def test_acquire_prompts_and_optionally_stores(tmp_path):
    key_file = tmp_path / "key"
    key, source = acquire_key(input_fn=lambda prompt: "prompted-key-999",
                              key_file=key_file, env={})
    assert key == "prompted-key-999" and source == "prompt+stored"
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    key2, source2 = acquire_key(input_fn=lambda prompt: (_ for _ in ()).throw(
        AssertionError("must not prompt when stored")),
        key_file=key_file, env={})
    assert (key2, source2) == ("prompted-key-999", "file")


def test_empty_prompt_yields_no_key(tmp_path):
    assert acquire_key(input_fn=lambda prompt: "  ",
                       key_file=tmp_path / "k", env={}) == (None, None)


def test_fingerprint_and_redact_never_expose(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY_ENV, "sk-secret-ABCDEFGH")
    vault = KeyVault(env=dict(os.environ))
    assert "ABCDEFGH" not in vault.show() and vault.show().endswith("(from env)")
    assert vault.redact("key=sk-secret-ABCDEFGH!") == "key=***!"
    assert vault.auth_header() == {"Authorization": "Bearer sk-secret-ABCDEFGH"}
    assert fingerprint("") == "(empty)"
