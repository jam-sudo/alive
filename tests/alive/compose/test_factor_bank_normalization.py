"""The registered factor-bank normalization, and the claim it exists to support.

Owner decision #7 (2026-08-21,
``docs/superpowers/2026-08-17-compose-ablation-ladder-decisions.md``). The
ablation ladder compares three arms whose penalties live in different units, and
an ARBITRARY factor-bank scale ``c`` moved two of them while leaving the headline
fixed. ``identification.lambda_scaling`` had already made the headline's penalty
relative, but **L2's registered ``tanh`` saturation has an intrinsic scale that no
penalty rescaling can absorb** — applying the headline's scale to L2 measurably
made it *worse*. The only remedy that reaches every arm is to remove ``c``
itself, which is what ``factor_bank_normalization: sigma_max_z_unit`` does.

Two things are pinned here and the second is the decision:

1. the bank is built with ``sigma_max(Z) == 1`` and records the scalar it
   removed, and the artifact refuses a bank normalized under any other rule; and
2. **every ladder arm is invariant to the input scale.** That invariance is true
   *by construction* once the normalizer is applied — the point of the test is
   that the cancellation is exact in floating point and that nothing downstream
   (the registered conditioning ceiling, the rank policy) changed meaning.

``cond(Phi)`` and ``rank`` are invariant to a uniform rescale, so the registered
ceiling keeps its exact meaning; :func:`test_normalization_leaves_cond_and_rank_alone`
is what stops that from being an assumption.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from alive.compose.config2 import Phase2ConfigError, load_compose_phase2_config
from alive.compose.identify import rank_diagnostics
from alive.compose.models import L1Model, L2Model, L3Model
from alive.compose.zfactor import (
    FACTOR_BANK_NORMALIZATION,
    _deserialize_gene_factor_bank,
    build_gene_factors,
)

_K, _ESM = 4, 2


def _inputs(n_genes=12, scale=1.0, seed=0):
    rng = np.random.default_rng(seed)
    genes = [f"G{i:02d}" for i in range(n_genes)]
    delta = {g: rng.normal(size=20) * scale for g in genes}
    seq = {g: rng.normal(size=8) * scale for g in genes}
    return delta, seq


def _bank(scale=1.0, n_genes=12, k=_K, seed=0):
    delta, seq = _inputs(n_genes=n_genes, scale=scale, seed=seed)
    return build_gene_factors(
        delta_by_gene=delta,
        sequence_by_gene=seq,
        k_total=k,
        esm_dim=_ESM,
        encoder_revision="rev",
        sequence_mapping_hash="a" * 64,
    )


def _matrix(bank):
    return np.array([bank.z_by_gene[g] for g in bank.gene_order], dtype=np.float64)


# --------------------------------------------------------------------------- #
# 1. the artifact
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("k", [4, 6, 8])
def test_every_bank_is_built_with_unit_sigma_max(k):
    z = _matrix(_bank(k=k, n_genes=16))
    assert float(np.linalg.svd(z, compute_uv=False)[0]) == pytest.approx(1.0, abs=1e-12)


def test_the_bank_records_the_scale_it_removed():
    """Provenance, not just a normalized number.

    Without the recorded scalar the artifact could not say what was divided out,
    and two banks built from differently-scaled inputs would be
    indistinguishable despite describing different measurements.
    """
    b1, b100 = _bank(scale=1.0), _bank(scale=100.0)
    assert b1.normalization == FACTOR_BANK_NORMALIZATION
    assert b100.normalization_scale == pytest.approx(100.0 * b1.normalization_scale, rel=1e-9)
    assert b1.checksum != b100.checksum, "the removed scale must reach the checksum"


def test_the_normalized_factors_are_identical_across_input_scales():
    """The whole point: an arbitrary input scale leaves no trace in ``z``."""
    z1, z100 = _matrix(_bank(scale=1.0)), _matrix(_bank(scale=100.0))
    assert np.allclose(z1, z100, rtol=0, atol=1e-12)


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_a_zero_bank_does_not_divide_by_zero():
    """``sigma_max == 0`` iff ``Z`` is identically zero, where every scale is a no-op.

    The rule has to stay total: a degenerate bank must produce a refusable
    artifact, not a ``nan`` one.
    """
    genes = [f"G{i:02d}" for i in range(12)]
    bank = build_gene_factors(
        delta_by_gene={g: np.zeros(20) for g in genes},
        sequence_by_gene={g: np.zeros(8) for g in genes},
        k_total=_K,
        esm_dim=_ESM,
        encoder_revision="rev",
        sequence_mapping_hash="a" * 64,
    )
    assert bank.normalization_scale == 1.0
    assert np.all(np.isfinite(_matrix(bank)))


# --------------------------------------------------------------------------- #
# 2. the artifact refuses what it must
# --------------------------------------------------------------------------- #
def test_a_bank_normalized_under_another_rule_is_refused():
    """The rule is REGISTERED, so a differently-scaled artifact is not consumable.

    Its own checksum would verify against itself, which is exactly why the name
    has to be checked rather than inferred.
    """
    report = _bank().report()
    report["normalization"] = "rms_z_unit"
    with pytest.raises(ValueError, match="factor-bank normalization must be"):
        _deserialize_gene_factor_bank(report)


@pytest.mark.parametrize(
    "value",
    [0.0, -1.0, float("nan"), float("inf"), True, "1.0"],
    ids=["zero", "negative", "nan", "inf", "bool", "str"],
)
def test_an_unusable_scale_is_refused(value):
    report = _bank().report()
    report["normalization_scale"] = value
    with pytest.raises(ValueError, match="normalization_scale must be"):
        _deserialize_gene_factor_bank(report)


# --------------------------------------------------------------------------- #
# 3. what must NOT have changed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("k", [4, 6])
@pytest.mark.parametrize("c", [1e-10, 1e10, None], ids=["tiny", "huge", "the-bank-s-own-scale"])
def test_normalization_leaves_cond_and_rank_alone(k, c):
    """The registered ceiling and rank policy keep their exact meaning.

    ``cond`` is a ratio of singular values and ``rank`` uses a tolerance
    RELATIVE to ``sigma_max`` (``identification.rank_tolerance_rule``), so both
    are invariant to a uniform rescale of ``Z``. That is what lets #7 move the
    bank scale without redefining a REGISTERED numeric criterion, and it is a
    property of ``rank_diagnostics``, not of the normalizer -- so it is asserted
    against a rescale, not against two banks.

    An earlier form of this test compared banks built at input scales 1.0 and
    100.0. Those banks are normalized, hence identical to 2.9e-15, so the
    comparison could not fail under ANY normalizer and asserted nothing. The
    rescales below are deliberately extreme: an absolute rank tolerance survives
    a factor of 100 and is caught only when ``sigma_min(Phi)`` is driven under
    it, which ``c = 1e-10`` does (``Phi`` is bilinear, so it scales as ``c**2``).
    """
    n = 14
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    bank = _bank(scale=1.0, n_genes=n, k=k)
    z = _matrix(bank)
    # ``c = None`` reconstructs the bank EXACTLY as it stood before normalization:
    # the rule divided by one scalar, so multiplying it back is not a stand-in.
    scale = bank.normalization_scale if c is None else c
    assert scale != 1.0, "a unit rescale would make this test vacuous"
    rescaled = z * scale

    d = rank_diagnostics(z, pairs)
    d_rescaled = rank_diagnostics(rescaled, pairs)
    assert d.rank == d_rescaled.rank
    assert d.sym_dim == d_rescaled.sym_dim
    assert float(d.condition_number) == pytest.approx(float(d_rescaled.condition_number), rel=1e-9)


# --------------------------------------------------------------------------- #
# 4. the decision itself: every ladder arm is now scale-free
# --------------------------------------------------------------------------- #
def _ladder_errors(bank_scale):
    """Fit all three ladder arms on a bank built from inputs scaled by ``bank_scale``."""
    n, p, lam = 14, 3, 0.01
    z = _matrix(_bank(scale=bank_scale, n_genes=n))
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    rng = np.random.default_rng(5)
    b = [(lambda m: (m + m.T) / 2)(rng.normal(size=(_K, _K))) for _ in range(p)]
    eps = np.array([[z[g] @ m @ z[h] for m in b] for g, h in pairs])
    cut = len(pairs) * 3 // 4
    train, test = pairs[:cut], pairs[cut:]
    out = []
    for model_cls in (L1Model, L2Model, L3Model):
        model = model_cls()
        model.fit(z, train, eps[:cut], lam=lam)
        pred = np.array([model.predict_eps(z, g, h) for g, h in test])
        out.append(float(np.sqrt(np.mean((pred - eps[cut:]) ** 2))))
    return out


def test_every_ladder_arm_is_invariant_to_the_input_scale():
    """Decision #7, stated as the property it was approved to buy.

    Before the normalizer, a pure units change left the headline fixed to
    ``3.6e-15`` while L2 moved 188% and L3 61% — so an L1-vs-L2/L3 comparison
    mixed architecture with an unregistered constant. All three now move by
    nothing. The invariance is true by construction; what this asserts is that
    the cancellation is EXACT in floating point, for arms whose penalties are not
    even in the same units.
    """
    a, b = _ladder_errors(1.0), _ladder_errors(100.0)
    for name, x, y in zip(("L1", "L2", "L3"), a, b, strict=True):
        assert y == pytest.approx(x, rel=1e-9), f"{name} still depends on the bank scale"


# --------------------------------------------------------------------------- #
# 5. the rule at the config boundary
# --------------------------------------------------------------------------- #
# The normalizer is enforced in TWO places -- the artifact (above) and the
# registered config -- and a rule is only registered if BOTH refuse a
# disagreeing value. Tested here rather than left to the artifact tests because
# a config that named a different rule would be accepted by a loader that only
# echoed it, and the bank would then be built under a name nothing checked.
def test_the_config_registers_the_normalization_rule():
    """The committed config and the code constant name the same rule.

    Two enforcement sites can only agree by construction if something asserts
    they do; otherwise the constant could drift from the preregistration and
    every artifact-level test would still pass.
    """
    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    assert cfg.factor_bank_normalization == FACTOR_BANK_NORMALIZATION == "sigma_max_z_unit"


def test_the_config_refuses_an_unregistered_normalization_value(tmp_path):
    """A registered string is only registered if a disagreeing config is refused."""
    raw = yaml.safe_load(open("configs/compose_k562_v1_phase2.yaml"))
    raw["identification"]["factor_bank_normalization"] = "rms_z_unit"
    path = tmp_path / "mutated.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(Phase2ConfigError, match="factor_bank_normalization must match"):
        load_compose_phase2_config(str(path))


def test_the_config_refuses_a_missing_normalization_value(tmp_path):
    """Silence is not a default. A bank scale that nothing registered is exactly
    the unregistered degree of freedom decision #7 exists to remove."""
    raw = yaml.safe_load(open("configs/compose_k562_v1_phase2.yaml"))
    del raw["identification"]["factor_bank_normalization"]
    path = tmp_path / "missing.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(Phase2ConfigError, match="factor_bank_normalization"):
        load_compose_phase2_config(str(path))
