"""Unreal mapping tests (conventions shared with the C++ client)."""

from types import SimpleNamespace

import pytest

from npc_cortex.adapters import unreal


def test_fvector_identity_on_components():
    assert unreal.vec_to_position(SimpleNamespace(x=1, y=2, z=3)) == (1.0, 2.0, 3.0)
    assert unreal.vec_to_position([1, 2, 3]) == (1.0, 2.0, 3.0)


def test_fvector2d_identity_on_components():
    assert unreal.vec_to_position(SimpleNamespace(x=4, y=5)) == (4.0, 5.0)


def test_position_round_trip():
    assert unreal.position_to_fvector((1.0, 2.0)) == (1.0, 2.0, 0.0)
    assert unreal.position_to_fvector((1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert unreal.position_to_fvector2d((1.0, 2.0, 3.0)) == (1.0, 2.0)


def test_bad_arity_rejected():
    with pytest.raises(ValueError):
        unreal.vec_to_position((1, 2, 3, 4))
