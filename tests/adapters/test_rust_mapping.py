"""Rust mapping tests (conventions shared with the Rust client)."""

from types import SimpleNamespace

import pytest

from npc_cortex.adapters import rust


def test_vec3_identity_on_components():
    assert rust.vec_to_position(SimpleNamespace(x=1, y=2, z=3)) == (1.0, 2.0, 3.0)
    assert rust.vec_to_position([1, 2, 3]) == (1.0, 2.0, 3.0)


def test_vec2_identity_on_components():
    assert rust.vec_to_position(SimpleNamespace(x=4, y=5)) == (4.0, 5.0)
    assert rust.vec_to_position((4, 5)) == (4.0, 5.0)


def test_position_round_trip():
    assert rust.position_to_vec3((1.0, 2.0)) == (1.0, 2.0, 0.0)
    assert rust.position_to_vec3((1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert rust.position_to_vec2((1.0, 2.0, 3.0)) == (1.0, 2.0)


def test_bad_arity_rejected():
    with pytest.raises(ValueError):
        rust.vec_to_position([1])
