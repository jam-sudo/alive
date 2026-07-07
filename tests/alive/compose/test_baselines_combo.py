"""Tests for COMPOSE Phase-2a combo baselines + guarded GEARS/CPA adapter seam.

Two concerns are covered:

* the lower-bound / null baselines (``additive``, ``no_change``,
  ``perturbation_mean``) are exact, symmetric, pure-``numpy`` functions; and
* the guarded ``BaselineAdapter`` seam (GEARS/CPA) fails closed. Activation is
  BLOCKED (no real ``gears``/``cpa`` deps), so the seam is exercised only with an
  in-test stub backend, and every leakage guard is proven to fire:

  - a context whose ``allowed_roles`` is not exactly ``{"singles",
    "combo_calibration"}`` is rejected;
  - a context carrying a sealed role / sealed key / sealed path *anywhere* in a
    nested structure is rejected (recursive scan);
  - an arbitrary untyped dictionary (not a ``BaselineTrainingContext``) is
    rejected;
  - a backend that returns extra / missing / misaligned pair predictions, or a
    wrong response dimension, is rejected;
  - a well-behaved stub backend with the allowed roles and exactly the requested
    canonical pair IDs succeeds.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.baselines_combo import (
    BaselineAdapter,
    BaselineTrainingContext,
    BaselineUnavailable,
    additive,
    no_change,
    perturbation_mean,
)

# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #

RESPONSE_DIM = 4
PAIRS = [("a", "b"), ("a", "c"), ("b", "c")]


def _allowed_context() -> BaselineTrainingContext:
    """A clean development-role context with exactly the allowed roles."""
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="pm-checksum",
        response_space_checksum="rs-checksum",
        training_pair_ids=(("a", "b"),),
        single_gene_ids=("a", "b", "c"),
    )


class _StubBackend:
    """In-test stand-in for a GEARS/CPA backend.

    Parameters
    ----------
    predictions : dict
        Mapping from canonical pair ID to a length-``response_dim`` vector. Used
        verbatim so individual tests can inject extra / missing / misaligned /
        wrong-dimension predictions.
    available : bool
        When ``False`` the backend reports itself unavailable (simulating a
        missing real ``gears``/``cpa`` package at activation).
    """

    def __init__(self, predictions: dict[tuple[str, str], np.ndarray], *, available: bool = True):
        self._predictions = predictions
        self._available = available

    @property
    def is_available(self) -> bool:
        return self._available

    def predict(
        self,
        context: BaselineTrainingContext,
        pair_ids: list[tuple[str, str]],
        response_dim: int,
    ) -> dict[tuple[str, str], np.ndarray]:
        return self._predictions


def _good_predictions() -> dict[tuple[str, str], np.ndarray]:
    return {p: np.arange(RESPONSE_DIM, dtype=float) + i for i, p in enumerate(PAIRS)}


# --------------------------------------------------------------------------- #
# lower-bound / null baselines
# --------------------------------------------------------------------------- #


def test_additive_is_sum_of_single_shifts():
    delta_g = np.array([1.0, 2.0, 3.0, 4.0])
    delta_h = np.array([0.5, 0.5, 0.5, 0.5])
    np.testing.assert_allclose(additive(delta_g, delta_h), delta_g + delta_h)


def test_additive_is_symmetric():
    delta_g = np.array([1.0, -2.0, 3.0, 0.0])
    delta_h = np.array([4.0, 4.0, -1.0, 2.0])
    np.testing.assert_array_equal(additive(delta_g, delta_h), additive(delta_h, delta_g))


def test_additive_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        additive(np.zeros(3), np.zeros(4))


def test_no_change_is_zeros_of_response_dim():
    out = no_change(RESPONSE_DIM)
    np.testing.assert_array_equal(out, np.zeros(RESPONSE_DIM))
    assert out.shape == (RESPONSE_DIM,)


def test_no_change_rejects_nonpositive_dim():
    with pytest.raises(ValueError):
        no_change(0)


def test_perturbation_mean_is_mean_over_training_doubles():
    train = np.array([[1.0, 1.0], [3.0, 5.0]])  # 2 training double shifts, dim 2
    np.testing.assert_allclose(perturbation_mean(train), np.array([2.0, 3.0]))


def test_perturbation_mean_rejects_empty():
    with pytest.raises(ValueError):
        perturbation_mean(np.zeros((0, 4)))


# --------------------------------------------------------------------------- #
# BaselineTrainingContext — frozen + exact fields + no seal handles
# --------------------------------------------------------------------------- #


def test_context_is_frozen():
    ctx = _allowed_context()
    with pytest.raises(Exception):
        ctx.allowed_roles = frozenset()  # type: ignore[misc]


def test_context_has_exactly_the_required_fields_and_no_seal_handles():
    expected = {
        "allowed_roles",
        "pair_manifest_checksum",
        "response_space_checksum",
        "training_pair_ids",
        "single_gene_ids",
    }
    fields = set(BaselineTrainingContext.__dataclass_fields__)
    assert fields == expected
    # explicitly NO outcome-store handle and NO sealed paths.
    assert "outcome_store" not in fields
    assert not any("seal" in f for f in fields)
    assert not any("path" in f for f in fields)


# --------------------------------------------------------------------------- #
# guarded adapter — role gate
# --------------------------------------------------------------------------- #


def test_adapter_requires_exact_allowed_roles():
    backend = _StubBackend(_good_predictions())
    adapter = BaselineAdapter(name="gears", backend=backend)
    # missing combo_calibration
    bad = BaselineTrainingContext(
        allowed_roles=frozenset({"singles"}),
        pair_manifest_checksum="pm",
        response_space_checksum="rs",
        training_pair_ids=(("a", "b"),),
        single_gene_ids=("a", "b", "c"),
    )
    with pytest.raises(ValueError):
        adapter.predict(bad, PAIRS, RESPONSE_DIM)


def test_adapter_rejects_superset_of_allowed_roles():
    backend = _StubBackend(_good_predictions())
    adapter = BaselineAdapter(name="cpa", backend=backend)
    bad = BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration", "extra_role"}),
        pair_manifest_checksum="pm",
        response_space_checksum="rs",
        training_pair_ids=(("a", "b"),),
        single_gene_ids=("a", "b", "c"),
    )
    with pytest.raises(ValueError):
        adapter.predict(bad, PAIRS, RESPONSE_DIM)


# --------------------------------------------------------------------------- #
# guarded adapter — recursive sealed-role / sealed-key / sealed-path rejection
# --------------------------------------------------------------------------- #


def test_adapter_rejects_sealed_role_in_allowed_roles():
    backend = _StubBackend(_good_predictions())
    adapter = BaselineAdapter(name="gears", backend=backend)
    bad = BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration", "sealed_double_unseen"}),
        pair_manifest_checksum="pm",
        response_space_checksum="rs",
        training_pair_ids=(("a", "b"),),
        single_gene_ids=("a", "b", "c"),
    )
    with pytest.raises(ValueError):
        adapter.predict(bad, PAIRS, RESPONSE_DIM)


def test_adapter_rejects_sealed_key_nested_in_checksum_value():
    backend = _StubBackend(_good_predictions())
    adapter = BaselineAdapter(name="gears", backend=backend)
    # a sealed token smuggled inside a string field, deep in the value
    bad = BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="ok",
        response_space_checksum="path/to/sealed_single_unseen.h5ad",
        training_pair_ids=(("a", "b"),),
        single_gene_ids=("a", "b", "c"),
    )
    with pytest.raises(ValueError):
        adapter.predict(bad, PAIRS, RESPONSE_DIM)


def test_recursive_sealed_scan_fires_on_deeply_nested_structure():
    # the standalone recursive scanner must find a sealed token nested inside
    # lists/dicts/tuples, not just at the top level.
    from alive.compose.baselines_combo import _assert_no_sealed_reference

    clean = {"a": [1, 2, {"b": ("c", "d")}], "e": "fine"}
    _assert_no_sealed_reference(clean)  # must NOT raise

    dirty_role = {"a": [1, {"b": ["x", "sealed_double_unseen"]}]}
    with pytest.raises(ValueError):
        _assert_no_sealed_reference(dirty_role)

    dirty_key = {"outer": {"sealed_single_unseen": [0]}}
    with pytest.raises(ValueError):
        _assert_no_sealed_reference(dirty_key)

    dirty_path = ["fine", ("also", "/data/sealed/double_unseen.npy")]
    with pytest.raises(ValueError):
        _assert_no_sealed_reference(dirty_path)


# --------------------------------------------------------------------------- #
# guarded adapter — untyped dict rejection
# --------------------------------------------------------------------------- #


def test_adapter_rejects_arbitrary_untyped_dict():
    backend = _StubBackend(_good_predictions())
    adapter = BaselineAdapter(name="gears", backend=backend)
    untyped = {
        "allowed_roles": ["singles", "combo_calibration"],
        "pair_manifest_checksum": "pm",
        "response_space_checksum": "rs",
        "training_pair_ids": [["a", "b"]],
        "single_gene_ids": ["a", "b", "c"],
    }
    with pytest.raises(TypeError):
        adapter.predict(untyped, PAIRS, RESPONSE_DIM)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# guarded adapter — backend output validation
# --------------------------------------------------------------------------- #


def test_adapter_rejects_extra_pair_predictions():
    preds = _good_predictions()
    preds[("a", "d")] = np.zeros(RESPONSE_DIM)  # not in requested PAIRS
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(preds))
    with pytest.raises(ValueError):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


def test_adapter_rejects_missing_pair_predictions():
    preds = _good_predictions()
    del preds[("b", "c")]  # a requested pair is absent
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(preds))
    with pytest.raises(ValueError):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


def test_adapter_rejects_wrong_response_dimension():
    preds = {p: np.zeros(RESPONSE_DIM + 1) for p in PAIRS}  # misaligned dim
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(preds))
    with pytest.raises(ValueError):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


def test_adapter_rejects_noncanonical_or_misaligned_pair_keys():
    preds = _good_predictions()
    # swap one key to its reversed (non-canonical) form
    val = preds.pop(("a", "b"))
    preds[("b", "a")] = val
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(preds))
    with pytest.raises(ValueError):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


def test_adapter_raises_unavailable_when_backend_missing():
    adapter = BaselineAdapter(name="gears", backend=None)
    with pytest.raises(BaselineUnavailable):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


def test_adapter_raises_unavailable_when_backend_reports_unavailable():
    backend = _StubBackend(_good_predictions(), available=False)
    adapter = BaselineAdapter(name="cpa", backend=backend)
    with pytest.raises(BaselineUnavailable):
        adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)


# --------------------------------------------------------------------------- #
# guarded adapter — happy path with a stub backend
# --------------------------------------------------------------------------- #


def test_adapter_succeeds_with_stub_backend_and_matching_ids():
    expected = _good_predictions()
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(expected))
    out = adapter.predict(_allowed_context(), PAIRS, RESPONSE_DIM)
    assert set(out.keys()) == set(PAIRS)
    for p in PAIRS:
        assert out[p].shape == (RESPONSE_DIM,)
        np.testing.assert_array_equal(out[p], expected[p])


def test_adapter_accepts_pairs_in_any_request_order():
    # requesting the same pairs in a permuted order still matches the backend.
    expected = _good_predictions()
    adapter = BaselineAdapter(name="cpa", backend=_StubBackend(expected))
    out = adapter.predict(_allowed_context(), list(reversed(PAIRS)), RESPONSE_DIM)
    assert set(out.keys()) == set(PAIRS)


# --------------------------------------------------------------------------- #
# D2 fresh-backend spawn contract
# --------------------------------------------------------------------------- #


class _SpawnableStub:
    """A backend stub that exposes the ``spawn(*, seed)`` fresh-instance contract."""

    def __init__(self, seed: int):
        self.seed = seed

    def spawn(self, *, seed: int) -> "_SpawnableStub":
        return _SpawnableStub(seed)


def test_adapter_spawn_delegates_to_backend_and_wraps_fresh_instance():
    backend = _SpawnableStub(seed=11)
    adapter = BaselineAdapter(name="gears", backend=backend)

    child = adapter.spawn(seed=23)

    assert isinstance(child, BaselineAdapter)
    assert child.name == "gears"
    assert child is not adapter
    # a genuinely fresh backend, seeded as requested, not the original instance.
    assert child.backend is not backend
    assert child.backend.seed == 23
    # spawning must not mutate the parent adapter or its backend.
    assert adapter.backend is backend
    assert backend.seed == 11


def test_adapter_spawn_rejects_backend_without_spawn():
    # _StubBackend exposes is_available + predict but NOT spawn: scientific D2
    # rejects it here, before any fit, so it can never enter a seed-variability run.
    adapter = BaselineAdapter(name="gears", backend=_StubBackend(_good_predictions()))
    with pytest.raises(TypeError, match="spawn"):
        adapter.spawn(seed=23)


def test_adapter_spawn_rejects_missing_backend():
    adapter = BaselineAdapter(name="cpa", backend=None)
    with pytest.raises(TypeError, match="spawn"):
        adapter.spawn(seed=23)
