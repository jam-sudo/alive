"""Real-Norman Φ rank + condition report on ``combo_calibration`` (§10.6).

This is the COMPOSE-K562-v1 activation-blocker deliverable
``real_norman_phi_rank_and_condition_report`` (spec §2.4 / §3.2 / §10.6): for
each registered total factor dimension ``k_total`` it builds the fixed per-gene
factor bank ``z_g = [PCA_k(δ_g) ; ESM-PCA(s_g)]`` (:func:`alive.compose.zfactor.
build_factor_grid`), forms the symmetric bilinear design matrix
``Φ = [vecsym(z_g z_hᵀ)]`` over the seeded ``combo_calibration`` pair set
(:func:`alive.compose.split.build_pair_split`), and reports its algebraic rank
versus the identifiable subspace dimension ``sym_dim = k(k+1)/2`` plus the
conditioning that governs noisy recovery (:func:`alive.compose.identify.
rank_diagnostics`).

The computation is outcome-free and opens NO seal: it consumes single-role
``δ_g`` and outcome-free ESM sequence vectors only, and the split is driven by a
seeded gene partition (never GI strength). The pure function here takes arrays
so it is unit-testable without real data or a real ESM model; the thin CLI
``scripts/compose_phi_rank_report.py`` assembles the real inputs.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from alive.compose.identify import rank_diagnostics
from alive.compose.roles import (
    CALIBRATION_ROLE_NAME,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
)
from alive.compose.split import build_pair_split
from alive.compose.zfactor import build_factor_grid

PHI_RANK_ACTIVATION_SCHEMA = "compose_phi_rank_report_v1"

_ENVELOPE_KEYS = frozenset(
    {
        "activation",
        "config_sha256",
        "data_sha256",
        "deliverable",
        "device",
        "esm_model",
        "generated_at_utc",
        "git_sha",
        "long_sequence_policy",
        "n_cells",
        "n_control_cells",
        "n_doubles_total",
        "n_eligible_genes",
        "n_singles_total",
        "n_z_universe_genes",
        "protocol",
        "report",
        "schema",
        "sequence_mapping_sha256",
    }
)
_REPORT_KEYS = frozenset(
    {
        "calibration_fraction",
        "esm_dim",
        "n_calibration_genes",
        "n_combo_calibration",
        "n_eligible_pairs",
        "n_sealed_double_unseen",
        "n_sealed_single_unseen",
        "per_k_total",
        "split_seed",
    }
)
_FACTOR_BLOCK_KEYS = frozenset(
    {
        "condition_number",
        "factor_bank_checksum",
        "is_full_rank",
        "k_total",
        "n_calibration_pairs_scored",
        "n_calibration_pairs_skipped",
        "n_genes",
        "rank",
        "sym_dim",
    }
)


def _exact_object(value: Any, expected: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    got = set(value)
    if got != expected:
        raise ValueError(
            f"{context} schema mismatch (missing={sorted(expected - got)}, "
            f"extra={sorted(got - expected)})"
        )
    return value


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _full_hex(value: Any, context: str, *, lengths: tuple[int, ...]) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in lengths
        or re.fullmatch(r"[0-9a-f]+", value) is None
    ):
        raise ValueError(f"{context} must be full lowercase hex")
    return value


def _validate_factor_block(
    block: Mapping[str, Any],
    *,
    expected_k: int,
    sym_dim: int,
    expected_scored_pairs: int,
    n_z_universe_genes: int,
) -> float:
    """Validate one ``per_k_total`` block and return its condition number as a float.

    Eleven distinct rejections, one message each. They were previously a single
    eleven-clause ``or`` behind the one string "invalid or non-full-rank factor
    block", so an operator whose pod run stopped here could not tell a RANK
    DEFICIENCY — the one cause that says the registered grid is misspecified —
    from a pair-count bookkeeping mismatch or a malformed condition number.

    The accepted set is **unchanged**: same conditions, same short-circuit order,
    same ``ValueError`` type. Only the messages are new. This is deliberate — the
    gate is fail-closed and splitting the message must not move the boundary.

    Parameters
    ----------
    block : Mapping
        One ``report.per_k_total`` entry, already schema-checked by
        :func:`_exact_object`.
    expected_k : int
        The registered ``total_k_grid`` position this block must occupy.
    sym_dim : int
        ``expected_k * (expected_k + 1) // 2``, the identifiable subspace
        dimension.
    expected_scored_pairs : int
        The report's own ``n_combo_calibration``.
    n_z_universe_genes : int
        The envelope's ``n_z_universe_genes``.

    Returns
    -------
    float
        The block's condition number, validated numeric, finite and positive.

    Raises
    ------
    ValueError
        With a cause-specific message for each of the eleven rejections.
    """
    at = f"phi-rank factor block k_total={expected_k}"
    # Every count and dimension is read through _nonnegative_int FIRST, so an
    # integer-VALUED float (4.0) or a bool (False for 0) is refused rather than
    # compared. A bare `!=` accepts both -- an exactness hole an external audit
    # found on 2026-08-17 by feeding this validator `k_total: 4.0` and
    # `n_calibration_pairs_skipped: False` and watching a "READY" report pass.
    # This DOES narrow the accepted set, deliberately and in the fail-closed
    # direction; it is the one place this file's "the boundary must not move"
    # rule is knowingly set aside, because the boundary was wrong.
    if _nonnegative_int(block["k_total"], f"{at}: k_total") != expected_k:
        raise ValueError(
            f"{at}: block k_total {block['k_total']!r} does not match its registered grid position"
        )
    if _nonnegative_int(block["sym_dim"], f"{at}: sym_dim") != sym_dim:
        raise ValueError(f"{at}: reported sym_dim {block['sym_dim']!r} is not k(k+1)/2 = {sym_dim}")
    rank = _nonnegative_int(block["rank"], f"{at}: rank")
    if rank > sym_dim:
        # A SEPARATE cause, not a deficiency. `rank <= min(n_pairs, sym_dim)`
        # always holds, so an over-rank block is not a design that failed to span
        # its subspace -- it is an internally inconsistent report. Folding it into
        # the deficiency branch made the message say "rank 37 is below sym_dim=36".
        raise ValueError(
            f"{at}: rank {rank} EXCEEDS the identifiable subspace dimension "
            f"sym_dim={sym_dim}; rank <= min(n_pairs, sym_dim) holds by construction, "
            "so this report is internally inconsistent"
        )
    if rank != sym_dim:
        raise ValueError(
            f"{at}: RANK-DEFICIENT — rank {rank} is below the identifiable "
            f"subspace dimension sym_dim={sym_dim}, so this registered grid point is "
            "not identifiable on the calibration design"
        )
    if block["is_full_rank"] is not True:
        raise ValueError(
            f"{at}: is_full_rank is {block['is_full_rank']!r}, not the boolean True "
            "(a truthy 1 is refused: the flag and the rank must agree exactly)"
        )
    scored = _nonnegative_int(
        block["n_calibration_pairs_scored"], f"{at}: n_calibration_pairs_scored"
    )
    if scored != expected_scored_pairs:
        raise ValueError(
            f"{at}: scored {scored} calibration pairs, "
            f"but the report declares n_combo_calibration={expected_scored_pairs}"
        )
    skipped = _nonnegative_int(
        block["n_calibration_pairs_skipped"], f"{at}: n_calibration_pairs_skipped"
    )
    if skipped != 0:
        raise ValueError(
            f"{at}: {skipped} calibration pairs were "
            "skipped; the design must be built on every calibration pair"
        )
    if _nonnegative_int(block["n_genes"], f"{at}: n_genes") != n_z_universe_genes:
        raise ValueError(
            f"{at}: factor bank covers {block['n_genes']!r} genes, but the envelope "
            f"declares n_z_universe_genes={n_z_universe_genes}"
        )
    condition = block["condition_number"]
    if isinstance(condition, bool):
        raise ValueError(f"{at}: condition_number is a boolean, not a number")
    if not isinstance(condition, (int, float)):
        raise ValueError(f"{at}: condition_number {condition!r} is not numeric")
    if not math.isfinite(float(condition)):
        raise ValueError(f"{at}: condition_number {condition!r} is not finite")
    if float(condition) <= 0.0:
        raise ValueError(f"{at}: condition_number {condition!r} is not positive")
    return float(condition)


def validate_phi_rank_activation_report(
    envelope: Any,
    *,
    expected_protocol: str,
    expected_config_sha256: str,
    expected_git_sha: str,
    expected_data_sha256: str,
    expected_sequence_mapping_sha256: str,
    expected_split_seed: int,
    expected_calibration_fraction: float,
    expected_total_k_grid: Sequence[int],
    expected_esm_model: str,
    expected_esm_dim: int,
    expected_condition_ceiling: float,
) -> dict[str, int]:
    """Validate a READY rank report and return its independently bound role counts.

    ``expected_condition_ceiling`` is the registered
    ``identification.condition_ceiling``. This report computes the SAME statistic
    on the SAME design as the admissibility screen in
    :func:`alive.compose.select.select_hyperparams`, so the two must agree — and
    agreeing means matching the screen's **ANY** rule, not an ALL rule. A single
    over-ceiling ``k_total`` is a dimension the run drops and proceeds without;
    only a grid with no admissible dimension at all is uncertifiable. Checking it
    here costs nothing and runs before an owner approves a SHA or a pod trip is
    spent.
    """
    # A nan/inf ceiling would silence this check on every block and a non-positive
    # one would reject every block; both are refused for the same reason the
    # selection screen refuses them. Production passes a loader-validated value,
    # so this is defence in depth on the argument, not on the config.
    ceiling = float(expected_condition_ceiling)
    if not math.isfinite(ceiling) or ceiling <= 0.0:
        raise ValueError(
            "phi-rank expected_condition_ceiling must be finite and positive, "
            f"got {expected_condition_ceiling!r}"
        )
    top = _exact_object(envelope, _ENVELOPE_KEYS, "phi-rank envelope")
    if top["schema"] != PHI_RANK_ACTIVATION_SCHEMA:
        raise ValueError("phi-rank schema mismatch")
    if top["deliverable"] != "real_norman_phi_rank_and_condition_report":
        raise ValueError("phi-rank deliverable mismatch")
    if top["protocol"] != expected_protocol:
        raise ValueError("phi-rank protocol mismatch")
    if not isinstance(top["activation"], str) or not top["activation"].upper().startswith("READY"):
        raise ValueError("phi-rank activation must start with 'READY'")
    if top["config_sha256"] != expected_config_sha256:
        raise ValueError("phi-rank config_sha256 mismatch")
    if top["data_sha256"] != expected_data_sha256:
        raise ValueError("phi-rank data_sha256 mismatch")
    _full_hex(top["config_sha256"], "phi-rank config_sha256", lengths=(64,))
    _full_hex(top["data_sha256"], "phi-rank data_sha256", lengths=(64,))
    _full_hex(top["sequence_mapping_sha256"], "phi-rank sequence mapping SHA", lengths=(64,))
    if top["sequence_mapping_sha256"] != expected_sequence_mapping_sha256:
        raise ValueError("phi-rank sequence mapping SHA mismatch")
    _full_hex(top["git_sha"], "phi-rank git_sha", lengths=(40, 64))
    if top["git_sha"] != expected_git_sha:
        raise ValueError("phi-rank git_sha mismatch")
    if not isinstance(top["generated_at_utc"], str) or not top["generated_at_utc"].strip():
        raise ValueError("phi-rank generated_at_utc must be non-empty")
    if top["esm_model"] != expected_esm_model:
        raise ValueError("phi-rank esm_model mismatch")
    if top["long_sequence_policy"] not in {"truncate", "error"}:
        raise ValueError("phi-rank long_sequence_policy is invalid")
    for field in (
        "n_cells",
        "n_control_cells",
        "n_doubles_total",
        "n_eligible_genes",
        "n_singles_total",
        "n_z_universe_genes",
    ):
        _nonnegative_int(top[field], f"phi-rank {field}")
    if top["n_z_universe_genes"] > top["n_eligible_genes"]:
        raise ValueError("phi-rank z-universe cannot exceed the eligible-gene universe")

    device = top["device"]
    if not isinstance(device, dict) or set(device) not in (
        {"cuda_available", "device_name", "torch_version"},
        {"cuda_available", "device_name", "error"},
    ):
        raise ValueError("phi-rank device provenance schema mismatch")
    if type(device["cuda_available"]) is not bool:  # noqa: E721 - reject int-as-bool
        raise ValueError("phi-rank device.cuda_available must be boolean")
    if not isinstance(device["device_name"], str) or not device["device_name"].strip():
        raise ValueError("phi-rank device_name must be non-empty")
    provenance_field = "torch_version" if "torch_version" in device else "error"
    if not isinstance(device[provenance_field], str) or not device[provenance_field].strip():
        raise ValueError(f"phi-rank device.{provenance_field} must be non-empty")

    report = _exact_object(top["report"], _REPORT_KEYS, "phi-rank report")
    if report["split_seed"] != expected_split_seed:
        raise ValueError("phi-rank split_seed mismatch")
    if report["calibration_fraction"] != expected_calibration_fraction:
        raise ValueError("phi-rank calibration_fraction mismatch")
    if report["esm_dim"] != expected_esm_dim:
        raise ValueError("phi-rank esm_dim mismatch")
    n_calibration_genes = _nonnegative_int(
        report["n_calibration_genes"], "phi-rank n_calibration_genes"
    )
    if n_calibration_genes > top["n_z_universe_genes"]:
        raise ValueError("phi-rank calibration-gene count exceeds its gene universe")
    pair_counts = {
        CALIBRATION_ROLE_NAME: _nonnegative_int(
            report["n_combo_calibration"], "phi-rank n_combo_calibration"
        ),
        SEALED_DOUBLE_UNSEEN_ROLE_NAME: _nonnegative_int(
            report["n_sealed_double_unseen"], "phi-rank n_sealed_double_unseen"
        ),
        SEALED_SINGLE_UNSEEN_ROLE_NAME: _nonnegative_int(
            report["n_sealed_single_unseen"], "phi-rank n_sealed_single_unseen"
        ),
    }
    if _nonnegative_int(report["n_eligible_pairs"], "phi-rank n_eligible_pairs") != sum(
        pair_counts.values()
    ):
        raise ValueError("phi-rank eligible-pair total is inconsistent")

    expected_grid = tuple(int(k) for k in expected_total_k_grid)
    per_k = report["per_k_total"]
    if not isinstance(per_k, list) or len(per_k) != len(expected_grid):
        raise ValueError("phi-rank factor-grid roster is incomplete")
    over_ceiling: list[tuple[int, float]] = []
    for raw_block, expected_k in zip(per_k, expected_grid, strict=True):
        block = _exact_object(raw_block, _FACTOR_BLOCK_KEYS, "phi-rank factor block")
        sym_dim = expected_k * (expected_k + 1) // 2
        # RANK is ALL while the ceiling below is ANY, and that asymmetry is a
        # registered owner decision (#5, 2026-08-16), not an oversight. Measured on
        # the committed real-Norman report: 41 calibration pairs, rank == sym_dim at
        # every registered k (10/21/36), so the ALL rule is DORMANT -- ALL and ANY
        # accept that report identically. The two gates also check different
        # matrices: this one sees the full calibration design at no lambda, while
        # the runtime policy sees each gene-disjoint TRAIN fold at lam == 0.0 only,
        # so matching the quantifier would not align them. A rank-deficient
        # registered k means the grid is misspecified; the honest remedy is to
        # change total_k_grid -- a new run identity with a visible record -- not to
        # run silently on a subset. See
        # docs/superpowers/2026-08-16-compose-activation-rank-rule-decision.md.
        condition = _validate_factor_block(
            block,
            expected_k=expected_k,
            sym_dim=sym_dim,
            expected_scored_pairs=pair_counts[CALIBRATION_ROLE_NAME],
            n_z_universe_genes=top["n_z_universe_genes"],
        )
        # Collected, NOT raised per block. The run's rule is ANY, not ALL: an
        # over-ceiling k_total is screened out of selection and the study proceeds
        # on the rest. Rejecting the whole report over one such dimension would
        # block a run that would have succeeded -- the exact over-strictness this
        # ceiling's own design was corrected for, one gate earlier. Only a grid
        # with NO admissible dimension makes the report uncertifiable, which is
        # the same condition that makes selection itself invalid.
        if condition > ceiling:
            over_ceiling.append((expected_k, condition))
        _full_hex(block["factor_bank_checksum"], "phi-rank factor-bank checksum", lengths=(64,))
    if over_ceiling and len(over_ceiling) == len(expected_grid):
        detail = ", ".join(f"k_total={k}: {c}" for k, c in over_ceiling)
        raise ValueError(
            "phi-rank reports no admissible factor dimension: every registered grid point "
            f"is full rank but conditioned above the registered ceiling {ceiling} ({detail}); "
            "the run's admissibility screen would reject all of them and selection itself "
            "would be invalid"
        )
    return pair_counts


def compute_phi_rank_report(
    *,
    delta_by_gene: Mapping[str, NDArray],
    sequence_by_gene: Mapping[str, NDArray],
    eligible_pairs: Sequence[tuple[str, str]],
    total_k_grid: Sequence[int],
    esm_dim: int,
    split_seed: int,
    calibration_fraction: float,
    encoder_revision: str,
    sequence_mapping_hash: str,
) -> dict:
    """Build the per-``k_total`` Φ rank/condition report on ``combo_calibration``.

    Parameters
    ----------
    delta_by_gene, sequence_by_gene : Mapping[str, numpy.ndarray]
        Single-role response-space shifts ``δ_g`` and outcome-free ESM sequence
        vectors ``s_g``, covering exactly the same gene set (forwarded to
        :func:`alive.compose.zfactor.build_factor_grid`).
    eligible_pairs : sequence of (str, str)
        The pre-registered eligible pair universe (eligibility decided before
        the split). Split into roles by a seeded gene partition.
    total_k_grid : sequence of int
        Registered total factor dimensions (e.g. ``(4, 6, 8)``).
    esm_dim : int
        ESM-PCA projection dimension shared across the grid.
    split_seed : int
        The pre-registered split seed.
    calibration_fraction : float
        The pre-registered calibration gene fraction (``0 < f < 1``).
    encoder_revision, sequence_mapping_hash : str
        Provenance fields forwarded to the factor banks.

    Returns
    -------
    dict
        Report with the split role counts and, per ``k_total``, the
        ``RankReport`` fields plus the scored calibration-pair count.
    """
    split = build_pair_split(
        list(eligible_pairs), seed=split_seed, calibration_fraction=calibration_fraction
    )
    banks = build_factor_grid(
        delta_by_gene=dict(delta_by_gene),
        sequence_by_gene=dict(sequence_by_gene),
        total_k_grid=tuple(int(k) for k in total_k_grid),
        esm_dim=int(esm_dim),
        encoder_revision=encoder_revision,
        sequence_mapping_hash=sequence_mapping_hash,
    )

    per_k: list[dict] = []
    for k_total in sorted(banks):
        bank = banks[k_total]
        gene_order = list(bank.gene_order)
        index_of = {gene: i for i, gene in enumerate(gene_order)}
        z = np.stack([np.asarray(bank.z_by_gene[g], dtype=np.float64) for g in gene_order])

        scored: list[tuple[int, int]] = []
        skipped = 0
        for g, h in split.combo_calibration:
            if g in index_of and h in index_of:
                scored.append((index_of[g], index_of[h]))
            else:  # pragma: no cover - eligible pairs are a subset of the gene universe
                skipped += 1

        report = rank_diagnostics(z, scored)
        per_k.append(
            {
                "k_total": int(k_total),
                "sym_dim": int(report.sym_dim),
                "rank": int(report.rank),
                "is_full_rank": bool(report.is_full_rank),
                "condition_number": float(report.condition_number),
                "n_calibration_pairs_scored": len(scored),
                "n_calibration_pairs_skipped": int(skipped),
                "n_genes": len(gene_order),
                "factor_bank_checksum": bank.checksum,
            }
        )

    return {
        "split_seed": int(split_seed),
        "calibration_fraction": float(calibration_fraction),
        "esm_dim": int(esm_dim),
        "n_eligible_pairs": len(split.combo_calibration)
        + len(split.sealed_double_unseen)
        + len(split.sealed_single_unseen),
        "n_combo_calibration": len(split.combo_calibration),
        "n_sealed_double_unseen": len(split.sealed_double_unseen),
        "n_sealed_single_unseen": len(split.sealed_single_unseen),
        "n_calibration_genes": len(split.combo_genes),
        "per_k_total": per_k,
    }
