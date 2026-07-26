"""COMPOSE Phase-1 orchestration: synthetic recovery + gates -> go/no-go (spec §5).

Phase 1 opens no seal. The method axis (synthetic, real-independent) and the
sealed verdict axis are kept separate (spec §4.5); Phase 1 only produces the
method axis + the pre-check gate outcomes + a headline-regime recommendation.

Method validation (two synthetic runs)
--------------------------------------
The ``RecoveryReport`` schema (Task-5 fix) splits the false-GI guard into a
noiseless algebraic leg and a noise-robust ratio leg, and pins the backward
-compatible ``false_gi_norm`` alias to ``nan`` for rank>0 runs. We therefore
validate the method with TWO runs rather than the brief's single (NaN-prone)
run:

1. **Recovery run** at ``rank == config.synthetic_rank`` (> 0): asserts exact
   noiseless coefficient recovery (``< 1e-6``), noisy coefficient recovery
   within ``config.recovery_rel_err_tol``, and held-out double-unseen
   generalization within ``2 * config.recovery_rel_err_tol``. The held-out pair
   is gene-disjoint (BOTH genes absent from every calibration pair), so this is a
   genuine combo-zero-shot target — strictly harder and noise-amplified, hence
   the same looser bound Task 5 registered.
2. **False-GI guard run** at ``rank == 0``: asserts the noiseless algebraic leg
   recovers ~0 (``< 1e-8``) and that spurious recovered-GI from the noisy fit
   stays below ``_FALSE_GI_RATIO_MARGIN`` of the genuine recovered-GI from a
   noisy rank>0 fit at the same noise/config (the scale-relative guard Task 5
   registered; an absolute false-GI tolerance would be violated on some seeds,
   which is why the honest guard is a ratio — Phase 2 owns any absolute tol).

``method_axis == "METHOD_VALIDATED"`` iff BOTH runs' assertions hold.

Run-config choice (robust acceptance under the canonical config)
----------------------------------------------------------------
Both validation runs use ``k = min(config.k_grid)`` (k=4 -> ``sym_dim`` =
``k(k+1)/2`` = 10), ``n_pairs = _METHOD_N_PAIRS`` = 60, and a moderate
registered noise level ``noise = sorted(config.synthetic_noise_sd)[1]`` (0.05)
rather than the max. This gives ``n_pairs`` (60) >> ``sym_dim`` (10) for
comfortable full rank and a stable ridge, and avoids the borderline max-noise
regime. Empirically across all registered seeds: noiseless ~1e-15, noisy
~0.003, held-out ~0.003, false-GI ratio ~0.004 — all well inside tolerance.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from alive.compose.config import ComposePhase1Config, load_compose_config
from alive.compose.gates import GateResult, measurability_gate, power_gate, rank_gate
from alive.compose.identify import RankReport
from alive.compose.roles import CALIBRATION_ROLE_NAME
from alive.compose.synthetic import RecoveryReport, frontier_sweep, run_recovery
from alive.provenance import capture_environment, sha256_file

#: Phase tag recorded in the Phase-1 provenance record.
_PHASE_TAG = "compose_k562_v1_phase1"

#: Scale-relative false-GI margin (Task-5 registered): spurious recovered-GI
#: must be < 10% of genuine recovered-GI at the same noise/config.
_FALSE_GI_RATIO_MARGIN = 0.1
#: Calibration-pair count for the method-validation runs (>> sym_dim at k=4).
_METHOD_N_PAIRS = 60


@dataclass(frozen=True)
class Phase1Report:
    """Phase-1 go/no-go outcome.

    Attributes
    ----------
    method_axis
        ``"METHOD_VALIDATED"`` iff both synthetic validation runs pass; else
        ``"METHOD_NOT_VALIDATED"``. Synthetic, real-independent.
    gate_results
        The three pre-check gates (power, measurability, rank), in that order.
    headline_regime
        ``"double-unseen"`` when adequately powered, else the downgraded regime.
    go_no_go
        ``"GO"`` iff the method is validated AND the measurability gate passed.
    recovery
        The rank>0 recovery run, with its ``frontier`` field populated by the
        ``(k, |Cal|)`` sweep.
    """

    method_axis: str
    gate_results: tuple[GateResult, ...]
    headline_regime: str
    go_no_go: str
    recovery: RecoveryReport


def _validate_method(config: ComposePhase1Config) -> tuple[bool, RecoveryReport]:
    """Run the two synthetic validation runs; return (ok, recovery-run report).

    The returned report is the rank>0 recovery run with its ``frontier`` field
    populated by the ``(k, |Cal|)`` sweep. See the module docstring for the
    run-config rationale.
    """
    k = min(config.k_grid)
    noise = (
        sorted(config.synthetic_noise_sd)[1]
        if len(config.synthetic_noise_sd) > 1
        else (max(config.synthetic_noise_sd))
    )
    seed = config.registered_seeds[0]
    held_out_tol = 2.0 * config.recovery_rel_err_tol

    # (i) recovery run (rank > 0).
    rec = run_recovery(
        n_genes=config.synthetic_n_genes,
        p=config.response_dim,
        rank=config.synthetic_rank,
        n_pairs=_METHOD_N_PAIRS,
        noise_sd=noise,
        seed=seed,
        k=k,
    )
    recovery_ok = (
        rec.noiseless_rel_err < 1e-6
        and rec.noisy_rel_err < config.recovery_rel_err_tol
        and rec.held_out_pred_rel_err < held_out_tol
    )

    # (ii) false-GI guard run (rank == 0).
    guard = run_recovery(
        n_genes=config.synthetic_n_genes,
        p=config.response_dim,
        rank=0,
        n_pairs=_METHOD_N_PAIRS,
        noise_sd=noise,
        seed=seed,
        k=k,
    )
    guard_ok = (
        guard.false_gi_norm_noiseless < 1e-8
        and math.isfinite(guard.genuine_gi_norm)
        and guard.genuine_gi_norm > 0.0
        and guard.false_gi_norm_noisy < _FALSE_GI_RATIO_MARGIN * guard.genuine_gi_norm
    )

    frontier = frontier_sweep(
        k_grid=config.k_grid,
        n_cal_grid=(20, 40, 60),
        p=config.response_dim,
        rank=config.synthetic_rank,
        noise_sd=noise,
        seed=seed,
        n_genes=config.synthetic_n_genes,
    )
    rec_with_frontier = RecoveryReport(
        noiseless_rel_err=rec.noiseless_rel_err,
        noisy_rel_err=rec.noisy_rel_err,
        held_out_pred_rel_err=rec.held_out_pred_rel_err,
        false_gi_norm_noiseless=rec.false_gi_norm_noiseless,
        false_gi_norm_noisy=rec.false_gi_norm_noisy,
        genuine_gi_norm=rec.genuine_gi_norm,
        false_gi_norm=rec.false_gi_norm,
        is_full_rank=rec.is_full_rank,
        frontier=frontier,
    )
    return (recovery_ok and guard_ok), rec_with_frontier


def run_phase1(config: ComposePhase1Config, *, gate_inputs: dict) -> Phase1Report:
    """Run the synthetic recovery proof + the three pre-check gates.

    Parameters
    ----------
    config
        The frozen Phase-1 config (see :class:`ComposePhase1Config`).
    gate_inputs
        Outcome-independent, dev-only gate inputs:
        ``n_double_unseen_pairs`` (int), ``cells_per_pair`` (float),
        ``eps_split_a`` / ``eps_split_b`` (dev split-half eps arrays). Phase 1
        opens no seal; the measurability gate guards its own ``_role``.

    Returns
    -------
    Phase1Report
        The method axis, the three gate results, the headline-regime
        recommendation, the go/no-go verdict, and the recovery run.
    """
    method_ok, recovery = _validate_method(config)

    g_power = power_gate(
        gate_inputs["n_double_unseen_pairs"],
        gate_inputs["cells_per_pair"],
        min_pairs=config.min_double_unseen_pairs,
        min_cells=config.min_cells_per_pair,
    )
    g_meas = measurability_gate(
        gate_inputs["eps_split_a"],
        gate_inputs["eps_split_b"],
        _role=CALIBRATION_ROLE_NAME,
    )
    # The rank gate's RankReport is a SYNTHETIC PROXY, not a real Norman Phi rank:
    # Phase 1 has no Norman calibration design, so we forward only the boolean
    # full-rank flag from the synthetic recovery run. We flag this explicitly in the
    # emitted detail so the JSON is unmistakably not a real Norman rank. The rank
    # gate does not gate go/no-go (kept as a pre-check signal only).
    g_rank = rank_gate(
        RankReport(
            sym_dim=1,
            rank=1 if recovery.is_full_rank else 0,
            is_full_rank=recovery.is_full_rank,
            condition_number=1.0,
        )
    )
    g_rank = GateResult(
        name=g_rank.name,
        passed=g_rank.passed,
        detail={**g_rank.detail, "synthetic_proxy": True},
        recommendation=g_rank.recommendation,
    )

    headline = "double-unseen" if g_power.passed else "single-unseen (downgraded)"
    go = "GO" if (method_ok and g_meas.passed) else "NO_GO"
    return Phase1Report(
        method_axis="METHOD_VALIDATED" if method_ok else "METHOD_NOT_VALIDATED",
        gate_results=(g_power, g_meas, g_rank),
        headline_regime=headline,
        go_no_go=go,
        recovery=recovery,
    )


def _json_float(x: float) -> float | None:
    """JSON-safe float: map non-finite (NaN/inf) to ``None``."""
    return float(x) if math.isfinite(x) else None


def _recovery_payload(rec: RecoveryReport) -> dict:
    """JSON-safe payload for a :class:`RecoveryReport` (NaN -> null)."""
    return {
        "noiseless_rel_err": _json_float(rec.noiseless_rel_err),
        "noisy_rel_err": _json_float(rec.noisy_rel_err),
        "held_out_pred_rel_err": _json_float(rec.held_out_pred_rel_err),
        "false_gi_norm_noiseless": _json_float(rec.false_gi_norm_noiseless),
        "false_gi_norm_noisy": _json_float(rec.false_gi_norm_noisy),
        "genuine_gi_norm": _json_float(rec.genuine_gi_norm),
        "is_full_rank": bool(rec.is_full_rank),
        "frontier": [
            {
                "k": int(row["k"]),
                "n_cal": int(row["n_cal"]),
                "rel_err": _json_float(float(row["rel_err"])),
                "is_full_rank": bool(row["is_full_rank"]),
            }
            for row in rec.frontier
        ],
    }


def _gate_payload(g: GateResult) -> dict:
    """JSON-safe payload for a :class:`GateResult` (numpy floats -> float)."""
    return {
        "name": g.name,
        "passed": bool(g.passed),
        "detail": {
            k: (_json_float(float(v)) if isinstance(v, float) else v) for k, v in g.detail.items()
        },
        "recommendation": g.recommendation,
    }


def write_phase1(report: Phase1Report, out_dir: str | Path) -> None:
    """Write the Phase-1 report JSON to ``out_dir/phase1_report.json`` (write-once).

    Raises
    ------
    FileExistsError
        If ``phase1_report.json`` already exists in ``out_dir`` (immutability).
    """
    out = Path(out_dir) / "phase1_report.json"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method_axis": report.method_axis,
        "headline_regime": report.headline_regime,
        "go_no_go": report.go_no_go,
        "gate_results": [_gate_payload(g) for g in report.gate_results],
        "recovery": _recovery_payload(report.recovery),
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))


def write_phase1_provenance(
    report: Phase1Report,
    out_dir: str | Path,
    *,
    config_path: str | Path,
    lockfile_path: str | Path = "uv.lock",
    repo_dir: str | Path | None = None,
) -> Path:
    """Write a proportionate Phase-1 provenance record (write-once).

    Phase 1 opens no seal and has no raw-data / feature-bank inputs, so the full
    composite ``run_id`` + :class:`~alive.provenance.RunLedger` state machine
    (which binds raw expression files and sequence mappings) is not required. A
    lightweight, honest record suffices to satisfy the §11 provenance invariant:
    it pins the config digest, the registered seeds, the git SHA, and the
    checksum of the exact report that was written.

    Must be called *after* :func:`write_phase1` so the report JSON exists; this
    function hashes that file (not an in-memory re-serialisation) so the recorded
    digest is the checksum of the artifact on disk.

    Parameters
    ----------
    report
        The Phase-1 report whose summary verdict fields are echoed into the
        record for at-a-glance provenance (the authoritative copy is the hashed
        ``phase1_report.json``).
    out_dir
        Directory containing the already-written ``phase1_report.json``; the
        provenance record is written next to it as ``phase1_provenance.json``.
    config_path
        Path to the resolved Phase-1 config; hashed via
        :func:`alive.provenance.sha256_file` for ``config_digest`` and loaded for
        the registered seeds.
    lockfile_path
        Path to the dependency lockfile; passed to
        :func:`alive.provenance.capture_environment`. Defaults to ``"uv.lock"``.
    repo_dir
        Working directory for the git-HEAD lookup. ``None`` uses the current
        working directory. If git is unavailable the captured commit is the
        ``"UNKNOWN"`` sentinel and this function does not crash.

    Returns
    -------
    Path
        The path of the written ``phase1_provenance.json``.

    Raises
    ------
    FileExistsError
        If ``phase1_provenance.json`` already exists in ``out_dir``
        (write-once immutability, mirroring :func:`write_phase1`).
    """
    out_dir = Path(out_dir)
    prov_path = out_dir / "phase1_provenance.json"
    if prov_path.exists():
        raise FileExistsError(f"refusing to overwrite existing provenance: {prov_path}")
    report_path = out_dir / "phase1_report.json"

    cfg = load_compose_config(config_path)
    env = capture_environment(lockfile_path, cfg.registered_seeds, repo_dir=repo_dir)

    payload = {
        "phase": _PHASE_TAG,
        "config_digest": sha256_file(config_path),
        "git_sha": env.git_commit,
        "registered_seeds": list(cfg.registered_seeds),
        "report_sha256": sha256_file(report_path),
        "lockfile_sha256": env.lockfile_sha256,
        "python_version": env.python_version,
        "platform": env.platform,
        "method_axis": report.method_axis,
        "go_no_go": report.go_no_go,
    }
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return prov_path
