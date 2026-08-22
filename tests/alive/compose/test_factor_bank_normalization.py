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

import dataclasses

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
    serialize_factor_bank_collection,
    verify_bank_normalization,
)
from alive.provenance import sha256_bytes, sha256_json

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


# --------------------------------------------------------------------------- #
# 6. the rule is enforced ON THE NUMBERS, at every door
# --------------------------------------------------------------------------- #
# 2026-08-22, from an external audit that reproduced it: a bank could declare
# `sigma_max_z_unit`, record a scale, carry a checksum that verifies against the
# declaring artifact, and be ACCEPTED with an actual sigma_max(Z) of 7.0. Every
# check that existed compared the bank with ITSELF -- the checksum recomputes
# from the same declared numbers, and phase2a's row loop binds the runtime
# matrix to those same numbers. An unnormalized bank and a matrix copied from it
# agree perfectly and are both wrong. The owner-approved decision was in the
# generator and in the config; nothing on the consumption side enforced it.
#
# Each forgery below is built to pass EVERY other check -- self-consistent
# checksum, matching gene universe, byte-identical runtime rows -- so that only
# the normalization check can reject it. A forgery that trips an older check
# would make these tests pass for the wrong reason.
def _forged_bank(factor=7.0, **kw):
    """A bank scaled off the unit sphere, with its own checksum recomputed."""
    honest = _bank(**kw)
    scaled = {g: np.ascontiguousarray(np.asarray(v) * factor) for g, v in honest.z_by_gene.items()}
    forged = dataclasses.replace(honest, z_by_gene=scaled, checksum="")
    return dataclasses.replace(forged, checksum=sha256_bytes(forged.artifact_bytes()))


def test_a_bank_whose_actual_sigma_max_is_not_one_is_refused():
    """Door A -- reading a serialized artifact back."""
    forged = _forged_bank()
    assert sha256_bytes(forged.artifact_bytes()) == forged.checksum, (
        "the forgery must be self-consistent, or the checksum check rejects it first "
        "and this test proves nothing about the normalization"
    )
    with pytest.raises(ValueError, match="actual sigma_max"):
        _deserialize_gene_factor_bank(forged.report())


def test_serializing_a_bank_whose_actual_sigma_max_is_not_one_is_refused():
    """Door C -- before bank objects become the durable carrier."""
    forged = _forged_bank()
    with pytest.raises(ValueError, match="actual sigma_max"):
        serialize_factor_bank_collection({forged.k_total: forged})


def test_the_check_accepts_every_honest_bank():
    """The other direction: the check must not reject what the builder makes.

    A refusal that also refuses honest banks is not a guard, it is an outage --
    and this repository has turned off a gate for exactly that reason before.
    """
    for k in (4, 6, 8):
        for scale in (1e-6, 1.0, 1e6):
            bank = _bank(k=k, n_genes=16, scale=scale)
            verify_bank_normalization(bank)
            _deserialize_gene_factor_bank(bank.report())
            serialize_factor_bank_collection({bank.k_total: bank})


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_the_degenerate_zero_bank_stays_consumable():
    """The builder leaves an identically-zero Z alone at scale 1.0, so the check
    must mirror that. Refusing it would make this library produce an artifact it
    cannot read back -- a contradiction, not a guard."""
    genes = [f"G{i:02d}" for i in range(12)]
    bank = build_gene_factors(
        delta_by_gene={g: np.zeros(20) for g in genes},
        sequence_by_gene={g: np.zeros(8) for g in genes},
        k_total=_K,
        esm_dim=_ESM,
        encoder_revision="rev",
        sequence_mapping_hash="a" * 64,
    )
    verify_bank_normalization(bank)
    assert _deserialize_gene_factor_bank(bank.report()).normalization_scale == 1.0


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_a_zero_bank_claiming_a_scale_other_than_one_is_refused():
    """The zero branch is an exemption for a shape the builder produces, not a
    hole: a zero bank that records a scale it could not have applied is a lie
    about provenance even though its factors are harmless."""
    genes = [f"G{i:02d}" for i in range(12)]
    bank = build_gene_factors(
        delta_by_gene={g: np.zeros(20) for g in genes},
        sequence_by_gene={g: np.zeros(8) for g in genes},
        k_total=_K,
        esm_dim=_ESM,
        encoder_revision="rev",
        sequence_mapping_hash="a" * 64,
    )
    lying = dataclasses.replace(bank, normalization_scale=3.0, checksum="")
    lying = dataclasses.replace(lying, checksum=sha256_bytes(lying.artifact_bytes()))
    with pytest.raises(ValueError, match="identically zero"):
        verify_bank_normalization(lying)


def test_phase2a_refuses_a_bank_whose_actual_sigma_max_is_not_one():
    """Door B -- bank objects handed straight to the pipeline.

    The forgery scales the runtime matrix by the SAME factor, so the row-for-row
    binding still passes byte for byte and the aggregate checksum is rebuilt.
    Only the normalization check can reject this.
    """
    from alive.compose.phase2a import HashMismatchError, _verify_factor_banks
    from tests.alive.compose.test_phase2a import _build_instance, _factor_banks, _inputs

    factor = 7.0
    inst = _build_instance(np.random.default_rng(57))
    base = _inputs(inst)
    unit = {
        k: np.ascontiguousarray(
            np.asarray(m, dtype=np.float64)
            / float(np.linalg.svd(np.asarray(m, dtype=np.float64), compute_uv=False)[0])
        )
        for k, m in base.factors_by_k.items()
    }
    honest_inputs = dataclasses.replace(base, factors_by_k=unit)
    honest_banks = _factor_banks(honest_inputs)
    bound = dataclasses.replace(
        honest_inputs,
        factor_banks_by_k=honest_banks,
        factor_checksum=sha256_json(
            {"factor_banks_by_k": {str(k): honest_banks[k].checksum for k in sorted(honest_banks)}}
        ),
    )
    _verify_factor_banks(bound, require_banks=True)  # control: the honest bind passes

    scaled_inputs = dataclasses.replace(
        base, factors_by_k={k: np.ascontiguousarray(m * factor) for k, m in unit.items()}
    )
    forged_banks = _factor_banks(scaled_inputs)
    forged = dataclasses.replace(
        scaled_inputs,
        factor_banks_by_k=forged_banks,
        factor_checksum=sha256_json(
            {"factor_banks_by_k": {str(k): forged_banks[k].checksum for k in sorted(forged_banks)}}
        ),
    )
    with pytest.raises(HashMismatchError, match="actual sigma_max"):
        _verify_factor_banks(forged, require_banks=True)
