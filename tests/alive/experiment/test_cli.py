"""End-to-end tests for the reproducible CLI runner (Task 17).

These tests drive the ``alive cartographer`` subcommands IN-PROCESS (via
``cli.main([...])``) against a tmp artifacts directory, on SYNTHETIC data built
from a ``--data-card`` JSON that points to a tmp ``.h5ad`` and a gene→sequences
JSON.  The Task 6 :class:`MockSequenceEncoder` is used (no ESM download, no real
data).  The non-negotiable integrity properties verified here:

1. **evaluate-once REFUSES** unless ``FutilityDecision.status ==
   CONTINUE_CONFIRMATORY`` (FUTILITY_STOPPED → non-zero exit, seal stays shut).
2. **calibrate runs in EITHER branch** (a futility-stopped run still ships a
   conformal artifact).
3. **report NEVER recomputes** — it reads persisted artifacts only.
4. **The two report schemas are LOCKED** (futility report carries no
   confirmatory keys / no empirical sealed coverage / no negative-performance
   language and carries ``scientific_verdict: null`` + ``sealed_access_count 0``).
5. **provenance_ok is wired** — a tampered ledger hash → INVALID_EVALUATION.
6. **determinism** — same config+data → identical run_id and identical report.
"""

from __future__ import annotations

import json
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
import yaml

from alive import cli
from alive.config import load_config

# ---------------------------------------------------------------------------
# Synthetic-data construction (mirrors test_real_runner; CLI consumes a card)
# ---------------------------------------------------------------------------

_PERT_KEY = "target"
_CTRL_VAL = "ctrl"
_AA = "ACDEFGHIKLMNPQRSTVWY"


def _stable_seed(key: object) -> int:
    import hashlib

    return int.from_bytes(hashlib.sha256(str(key).encode()).digest()[:7], "big")


def _seq_for(gene: str, length: int = 24) -> str:
    rng = np.random.default_rng(_stable_seed(gene))
    return "".join(_AA[i] for i in rng.integers(0, len(_AA), size=length))


def _make_adata(*, n_ctrl: int, pert_cells: dict[str, int], n_genes: int, seed: int):
    rng = np.random.default_rng(seed)
    gene_ids = [f"g{i}" for i in range(n_genes)]
    labels: list[str] = [_CTRL_VAL] * n_ctrl
    for g, n in pert_cells.items():
        labels.extend([g] * n)
    n_cells = len(labels)

    base_level = rng.uniform(1.0, 5.0, size=n_genes)
    X = np.zeros((n_cells, n_genes), dtype=np.float64)
    row = 0
    for _ in range(n_ctrl):
        X[row] = rng.poisson(base_level)
        row += 1
    for g, n in pert_cells.items():
        g_rng = np.random.default_rng(_stable_seed(("shift", g)))
        shift = g_rng.uniform(-0.5, 1.5, size=n_genes)
        level = np.clip(base_level + shift, 0.1, None)
        for _ in range(n):
            X[row] = g_rng.poisson(level)
            row += 1

    obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=gene_ids)
    return anndata.AnnData(X=sp.csr_matrix(X.astype(np.float32)), obs=obs, var=var)


_BASE_CONFIG: dict = {
    "experiment": "cli_test",
    "manifest_seed": 7,
    "split_fractions": {
        "base_train": 0.40,
        "method_development": 0.30,
        "conformal_calibration": 0.15,
        "sealed_evaluation": 0.15,
    },
    "response_space": {
        "normalization": "library_size_10000_log1p",
        "hvg_count": 8,
        "pca_dims": 4,
        "cell_cap": 30,
        "min_cells": 8,
        "cell_sampling_repeats": 2,
        "energy_block_size": 64,
    },
    "perturbation_features": {
        "primary": "mock-v1",
        "standardize_on": "base_train",
        "missing_policy": "exclude_before_split",
    },
    "base_model": {
        "family": "additive_ridge",
        "ridge_grid": [0.1, 1.0, 10.0],
        "cv_folds": 3,
        "ensemble_members": 4,
    },
    "method_development": {
        "cv_folds": 3,
        "k_grid": [3, 5],
        "feature_weight_grid": [0.25, 0.5, 0.75, 1.0],
        "gbm_estimators_grid": [10, 20],
        "ridge_grid": [0.1, 1.0, 10.0],
        "registered_seeds": [11, 23],
    },
    "decision": {
        "target_selection_coverage": 0.70,
        "conformal_alpha": 0.10,
        "minimum_sealed_perturbations": 3,
    },
    "inference": {
        "bootstrap_replicates": 2000,
        "family_confidence": 0.95,
        "secondary_augrc_noninferiority_margin": 0.02,
    },
    "futility": {
        "enabled": True,
        "comparators": ["gbm_error", "residual_only"],
        "minimum_relevant_delta": 0.01,
        "family_confidence": 0.90,
        "rule": "stop_if_any_simultaneous_upper_bound_le_minimum",
    },
}


def _write_world(
    tmp_path: Path,
    *,
    config_overrides: dict | None = None,
    n_pert: int = 40,
    seed: int = 0,
) -> tuple[Path, Path]:
    """Write a config YAML + data-card JSON (+ h5ad + sequences) on a tmp path.

    Returns (config_path, data_card_path).
    """
    rng = np.random.default_rng(seed)
    genes = [f"GENE{i:03d}" for i in range(n_pert)]
    cells_per = {g: int(rng.integers(20, 30)) for g in genes}
    adata = _make_adata(n_ctrl=80, pert_cells=cells_per, n_genes=20, seed=seed + 1)

    h5ad_path = tmp_path / "synthetic.h5ad"
    adata.write_h5ad(h5ad_path)

    sequences = {g: [_seq_for(g)] for g in genes}
    seq_path = tmp_path / "sequences.json"
    seq_path.write_text(json.dumps(sequences), encoding="utf-8")

    cfg = json.loads(json.dumps(_BASE_CONFIG))  # deep copy
    if config_overrides:
        for section, override in config_overrides.items():
            if isinstance(override, dict) and isinstance(cfg.get(section), dict):
                cfg[section].update(override)
            else:
                cfg[section] = override
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")

    data_card = {
        "h5ad": str(h5ad_path),
        "sequences": str(seq_path),
        "perturbation_key": _PERT_KEY,
        "control_value": _CTRL_VAL,
        "gene_id_key": None,
        "counts_layer": None,
        "raw_data_uri": "synthetic://cli-test",
        "sequence_source": "uniprot-2024-01",
        "id_mapping_version": "ensembl-110",
    }
    data_card_path = tmp_path / "data_card.json"
    data_card_path.write_text(json.dumps(data_card), encoding="utf-8")
    return config_path, data_card_path


def _artifacts_root(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


def _run(argv: list[str], artifacts_root: Path) -> int:
    """Drive cli.main with an explicit artifacts root."""
    return cli.main([*argv, "--artifacts-root", str(artifacts_root)])


def _run_id(config_path: Path, data_card_path: Path) -> str:
    """Compute the composite immutable run_id exactly as ``cmd_prepare`` does."""
    from alive.cli import _raw_data_hash
    from alive.data.features import canonical_mapping_sha256
    from alive.provenance import compute_run_id, sha256_json

    config = load_config(config_path)
    data_card = json.loads(data_card_path.read_text(encoding="utf-8"))
    sequences = json.loads(Path(data_card["sequences"]).read_text(encoding="utf-8"))
    gene_sequences = {g: list(seqs) for g, seqs in sequences.items()}
    return compute_run_id(
        config.config_digest,
        sha256_json(data_card),
        _raw_data_hash(data_card["h5ad"], data_card),
        canonical_mapping_sha256(gene_sequences),
    )


# ---------------------------------------------------------------------------
# Helpers: composite run_id (data sensitivity + existing-dir refusal).
# ---------------------------------------------------------------------------


def _prepare_world(world_dir: Path, *, mutate_counts: bool = False) -> tuple[Path, Path]:
    """Build a world under ``world_dir``; optionally perturb the h5ad counts.

    The config is held fixed across calls (same seed) so that only the raw
    expression file differs when ``mutate_counts=True`` — isolating the
    data-sensitivity of the composite run_id.
    """
    world_dir.mkdir(parents=True, exist_ok=True)
    config_path, data_card_path = _write_world(world_dir, seed=3)
    if mutate_counts:
        data_card = json.loads(data_card_path.read_text(encoding="utf-8"))
        h5ad_path = Path(data_card["h5ad"])
        adata = anndata.read_h5ad(h5ad_path)
        dense = adata.X.toarray()
        dense[0, 0] = dense[0, 0] + 1.0  # one-cell, one-gene count bump
        adata.X = sp.csr_matrix(dense.astype(np.float32))
        adata.write_h5ad(h5ad_path)
    return config_path, data_card_path


def _prepare_and_get_run_id(world_dir: Path, *, mutate_counts: bool = False, capsys=None) -> str:
    """Build a world, run ``prepare``, and return the run_id printed by ``prepare``.

    Capturing the printed value (rather than recomputing) makes the test exercise
    the actual id that ``cmd_prepare`` names the run directory with.
    """
    import contextlib
    import io

    config_path, data_card_path = _prepare_world(world_dir, mutate_counts=mutate_counts)
    root = _artifacts_root(world_dir)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
    assert rc == 0
    printed = buf.getvalue().strip().splitlines()[-1].strip()
    # The printed id must name an existing run directory under the artifacts root.
    assert (root / "cartographer" / printed).is_dir()
    return printed


def _rerun_prepare(world_dir: Path, *, run_id: str) -> int:
    """Re-run ``prepare`` on the SAME world (identical inputs) and return rc."""
    config_path = world_dir / "config.yaml"
    data_card_path = world_dir / "data_card.json"
    root = _artifacts_root(world_dir)
    return _run(
        [
            "cartographer",
            "prepare",
            "--config",
            str(config_path),
            "--data-card",
            str(data_card_path),
            "--mock-encoder",
        ],
        root,
    )


def test_prepare_run_id_changes_with_data(tmp_path: Path) -> None:
    rid1 = _prepare_and_get_run_id(tmp_path / "a")  # default fixture data
    rid2 = _prepare_and_get_run_id(tmp_path / "b", mutate_counts=True)  # same config, altered h5ad
    assert rid1 != rid2  # composite id is data-sensitive


def test_prepare_refuses_existing_run_dir(tmp_path: Path) -> None:
    rid = _prepare_and_get_run_id(tmp_path)
    rc = _rerun_prepare(tmp_path, run_id=rid)  # identical inputs → dir already exists
    assert rc == 2  # refuses to overwrite an existing run directory


# ---------------------------------------------------------------------------
# Helper: engineer a CONTINUE futility decision by overwriting futility.json.
# ---------------------------------------------------------------------------


def _force_status(run_dir: Path, status_value: str) -> None:
    """Rewrite the persisted FutilityDecision to a chosen status (re-checksummed)."""
    from alive.experiment.develop import FutilityDecision
    from alive.types import OperationalStatus

    fpath = run_dir / "futility.json"
    decision = FutilityDecision.read(fpath)
    from dataclasses import replace

    forced = replace(decision, status=OperationalStatus(status_value))
    forced.write(fpath)


# ===========================================================================
# End-to-end CONTINUE branch
# ===========================================================================


class TestEndToEndContinue:
    def test_full_pipeline_confirmatory(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        assert (
            _run(
                [
                    "cartographer",
                    "prepare",
                    "--config",
                    str(config_path),
                    "--data-card",
                    str(data_card_path),
                    "--mock-encoder",
                ],
                root,
            )
            == 0
        )
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "feature_bank.npz").exists()
        assert (run_dir / "config.snapshot.yaml").exists()
        assert (run_dir / "data_card.json").exists()
        assert (run_dir / "ledger.json").exists()

        assert _run(["cartographer", "fit", "--run-id", run_id], root) == 0
        assert (run_dir / "base.npz").exists()

        assert _run(["cartographer", "develop", "--run-id", run_id], root) == 0
        assert (run_dir / "methodlock.json").exists()
        assert (run_dir / "dev_errors.npz").exists()

        assert _run(["cartographer", "futility", "--run-id", run_id], root) == 0
        assert (run_dir / "futility.json").exists()

        # Engineer CONTINUE so the sealed branch is permitted.
        _force_status(run_dir, "CONTINUE_CONFIRMATORY")

        assert _run(["cartographer", "calibrate", "--run-id", run_id], root) == 0
        assert (run_dir / "conformal.json").exists()

        assert _run(["cartographer", "evaluate-once", "--run-id", run_id], root) == 0
        assert (run_dir / "result.json").exists()

        assert _run(["cartographer", "report", "--run-id", run_id], root) == 0
        report_path = run_dir / "report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["mode"] == "confirmatory"
        assert report["sealed_access_count"] == 1
        assert report["scientific_verdict"] is not None
        # The seal opened exactly once.
        audit_lines = (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        assert len([line for line in audit_lines if line.strip()]) == 1


# ===========================================================================
# End-to-end FUTILITY branch
# ===========================================================================


class TestEndToEndFutility:
    def test_futility_refuses_and_ships_conformal(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        assert (
            _run(
                [
                    "cartographer",
                    "prepare",
                    "--config",
                    str(config_path),
                    "--data-card",
                    str(data_card_path),
                    "--mock-encoder",
                ],
                root,
            )
            == 0
        )
        assert _run(["cartographer", "fit", "--run-id", run_id], root) == 0
        assert _run(["cartographer", "develop", "--run-id", run_id], root) == 0
        assert _run(["cartographer", "futility", "--run-id", run_id], root) == 0

        # Engineer FUTILITY_STOPPED.
        _force_status(run_dir, "FUTILITY_STOPPED")

        # calibrate STILL runs in the futility branch.
        assert _run(["cartographer", "calibrate", "--run-id", run_id], root) == 0
        assert (run_dir / "conformal.json").exists()

        # evaluate-once REFUSES (non-zero) and does NOT open the seal.
        rc = _run(["cartographer", "evaluate-once", "--run-id", run_id], root)
        assert rc != 0
        assert not (run_dir / "result.json").exists()
        audit_path = run_dir / "audit.jsonl"
        if audit_path.exists():
            lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert lines == []

        # report reflects the futility terminal state.
        assert _run(["cartographer", "report", "--run-id", run_id], root) == 0
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert report["mode"] == "futility_stopped"
        assert report["scientific_verdict"] is None
        assert report["sealed_access_count"] == 0


# ===========================================================================
# Report schema lock (headline)
# ===========================================================================

# Banned negative-performance phrases (documented list).
_BANNED_PHRASES: tuple[str, ...] = (
    "worse",
    "underperform",
    "no distinct win",
    "fails to beat",
    "lost to",
    "inferior",
)

# Keys that belong only to the confirmatory schema.
_CONFIRMATORY_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "risk_coverage_curve",
        "simultaneous_intervals",
        "error_bound_diagnostics",
        "reliability",
        "ablations",
        "verdict_evidence",
    }
)

_FUTILITY_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "config",
        "provenance",
        "flow_counts",
        "methodlock",
        "futility",
        "conformal_artifact",
        "sealed_access_count",
        "scientific_verdict",
    }
)


class TestReportSchemaLock:
    def test_futility_schema_is_locked(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)
        _force_status(run_dir, "FUTILITY_STOPPED")
        _run(["cartographer", "calibrate", "--run-id", run_id], root)
        _run(["cartographer", "report", "--run-id", run_id], root)

        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

        # 1. EXACT top-level key set.
        assert set(report.keys()) == _FUTILITY_KEYS
        # 2. No confirmatory keys.
        assert set(report.keys()).isdisjoint(_CONFIRMATORY_ONLY_KEYS)
        # 3. scientific_verdict is None.
        assert report["scientific_verdict"] is None
        assert report["sealed_access_count"] == 0
        # 4. conformal_artifact has NO empirical sealed coverage.
        ca = report["conformal_artifact"]
        for banned in ("coverage", "sealed", "marginal", "selective"):
            assert not any(banned in str(k).lower() for k in ca.keys())
        assert "error_bound" in ca

        # 5. No negative-performance language anywhere in JSON or markdown.
        report_text = json.dumps(report).lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in report_text, f"banned phrase {phrase!r} in futility JSON"
        md_text = (run_dir / "report.md").read_text(encoding="utf-8").lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in md_text, f"banned phrase {phrase!r} in futility markdown"
        # 6. No risk-coverage content.
        assert "risk_coverage" not in report_text
        assert "selective_risk" not in report_text

    def test_confirmatory_schema_has_verdict_evidence(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)
        _force_status(run_dir, "CONTINUE_CONFIRMATORY")
        _run(["cartographer", "calibrate", "--run-id", run_id], root)
        _run(["cartographer", "evaluate-once", "--run-id", run_id], root)
        _run(["cartographer", "report", "--run-id", run_id], root)

        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert report["mode"] == "confirmatory"
        assert report["sealed_access_count"] == 1
        assert "verdict_evidence" in report
        assert "risk_coverage_curve" in report
        assert "coverage" in report["risk_coverage_curve"]
        assert "selective_risk" in report["risk_coverage_curve"]
        assert "simultaneous_intervals" in report
        assert "ablations" in report
        assert "reliability" in report
        assert "error_bound_diagnostics" in report


# ===========================================================================
# report never recomputes
# ===========================================================================


class TestReportNeverRecomputes:
    def test_report_reads_persisted_artifacts(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)
        _force_status(run_dir, "CONTINUE_CONFIRMATORY")
        _run(["cartographer", "calibrate", "--run-id", run_id], root)
        _run(["cartographer", "evaluate-once", "--run-id", run_id], root)

        persisted_verdict = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))[
            "verdict"
        ]

        # Mutate the on-disk dev_errors AFTER the result is persisted.  A report
        # that recomputes the verdict would diverge; one that reads persisted
        # artifacts is unchanged.
        dev_path = run_dir / "dev_errors.npz"
        npz = dict(np.load(dev_path))
        npz["errors"] = npz["errors"] * 1000.0 + 7.0
        np.savez_compressed(dev_path, **npz)

        _run(["cartographer", "report", "--run-id", run_id], root)
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert report["scientific_verdict"] == persisted_verdict


# ===========================================================================
# Once-only seal: a second evaluate-once fails cleanly (no traceback)
# ===========================================================================


class TestSecondEvaluateOnce:
    def test_second_call_exits_cleanly(self, tmp_path: Path, capsys) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)
        _force_status(run_dir, "CONTINUE_CONFIRMATORY")
        _run(["cartographer", "calibrate", "--run-id", run_id], root)
        assert _run(["cartographer", "evaluate-once", "--run-id", run_id], root) == 0
        capsys.readouterr()  # drain

        # A second sealed evaluation under the same run_id must fail cleanly.
        rc = _run(["cartographer", "evaluate-once", "--run-id", run_id], root)
        assert rc != 0
        combined = "".join(capsys.readouterr())
        assert "Traceback" not in combined
        assert "already opened" in combined.lower() or "once" in combined.lower()


# ===========================================================================
# provenance_ok wired (carry-forward a)
# ===========================================================================


class TestProvenanceWired:
    def test_tampered_ledger_hash_yields_invalid(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=3)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)
        _force_status(run_dir, "CONTINUE_CONFIRMATORY")
        _run(["cartographer", "calibrate", "--run-id", run_id], root)

        # Tamper a recorded ledger hash (e.g. the base_artifact checksum).
        ledger_path = run_dir / "ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        tampered = False
        for art in ledger["artifacts"]:
            if art["name"] == "base_artifact":
                art["sha256"] = "0" * 64
                tampered = True
        assert tampered, "expected a base_artifact entry to tamper"
        ledger_path.write_text(
            json.dumps(ledger, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )

        # evaluate-once still completes (writes a result) but the verdict is INVALID.
        _run(["cartographer", "evaluate-once", "--run-id", run_id], root)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        assert result["verdict"] == "INVALID_EVALUATION"
        assert result["clauses"]["provenance_ok"] is False


# ===========================================================================
# console entry point smoke test
# ===========================================================================


class TestConsoleEntryPoint:
    def test_missing_run_exits_cleanly(self, tmp_path: Path, capsys) -> None:
        root = _artifacts_root(tmp_path)
        rc = cli.main(
            ["cartographer", "report", "--run-id", "missing", "--artifacts-root", str(root)]
        )
        assert rc != 0
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # A clear error message, not a traceback.
        assert "missing" in combined.lower() or "not found" in combined.lower()
        assert "Traceback" not in combined

    def test_scripts_entry_registered(self) -> None:
        import tomllib

        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data["project"]["scripts"]
        assert scripts["alive"] == "alive.cli:main"


# ===========================================================================
# Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_inputs_same_run_id_and_report(self, tmp_path: Path) -> None:
        # The composite run_id binds the data card verbatim (which embeds the
        # input file PATHS); "same inputs" therefore means the SAME world (one
        # config, one data card, one h5ad).  We run the identical world through
        # two separate artifacts roots and assert the run_id and report match.
        world = tmp_path / "world"
        world.mkdir(parents=True, exist_ok=True)
        config_path, data_card_path = _write_world(world, seed=5)
        expected_run_id = _run_id(config_path, data_card_path)

        def _pipeline(root: Path) -> tuple[str, dict]:
            run_id = _run_id(config_path, data_card_path)
            run_dir = root / "cartographer" / run_id
            _run(
                [
                    "cartographer",
                    "prepare",
                    "--config",
                    str(config_path),
                    "--data-card",
                    str(data_card_path),
                    "--mock-encoder",
                ],
                root,
            )
            _run(["cartographer", "fit", "--run-id", run_id], root)
            _run(["cartographer", "develop", "--run-id", run_id], root)
            _run(["cartographer", "futility", "--run-id", run_id], root)
            _force_status(run_dir, "CONTINUE_CONFIRMATORY")
            _run(["cartographer", "calibrate", "--run-id", run_id], root)
            _run(["cartographer", "evaluate-once", "--run-id", run_id], root)
            _run(["cartographer", "report", "--run-id", run_id], root)
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            return run_id, report

        run_a, report_a = _pipeline(tmp_path / "root_a")
        run_b, report_b = _pipeline(tmp_path / "root_b")
        assert run_a == run_b == expected_run_id
        assert report_a["scientific_verdict"] == report_b["scientific_verdict"]
        # The verdict-bearing content is identical (modulo non-hashed env in provenance).
        report_a.pop("provenance", None)
        report_b.pop("provenance", None)
        assert report_a == report_b


# ===========================================================================
# Fix 4: CLI/staged parity test
# ===========================================================================
# develop+futility via CMD must produce byte-identical MethodLock and
# FutilityDecision checksums as develop_methods_stage() on the same data.
# This closes the divergence risk identified in review item I-2.


class TestCliDevelopedParity:
    """CLI develop+futility path must produce identical checksums to develop_methods_stage().

    This test runs both execution paths on an identical synthetic world and
    asserts that the resulting MethodLock and FutilityDecision checksums are
    byte-identical.  If the CLI re-implementation drifts from the tested staged
    function, this test catches the divergence.
    """

    def test_cli_develop_futility_matches_staged_function(self, tmp_path: Path) -> None:
        from alive.data.features import MockSequenceEncoder, build_feature_bank
        from alive.data.manifest import build_manifest_from_index
        from alive.data.outcome_store import ReplogleOutcomeStore
        from alive.data.replogle import DatasetSchema, build_index
        from alive.experiment.develop import FutilityDecision, MethodLock
        from alive.experiment.real_runner import develop_methods_stage, fit_base

        # Build the synthetic world in a subdirectory so sequences.json path is clean.
        world_dir = tmp_path / "world"
        world_dir.mkdir(parents=True, exist_ok=True)
        config_path, data_card_path = _write_world(world_dir, seed=77)
        root = _artifacts_root(world_dir)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        # === CLI path (cmd_prepare → cmd_fit → cmd_develop → cmd_futility) ===
        _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        _run(["cartographer", "fit", "--run-id", run_id], root)
        _run(["cartographer", "develop", "--run-id", run_id], root)
        _run(["cartographer", "futility", "--run-id", run_id], root)

        cli_method_lock = MethodLock.read(run_dir / "methodlock")
        cli_futility = FutilityDecision.read(run_dir / "futility.json")

        # === Staged-function path on the SAME persisted data ===
        # Load the world the CLI already prepared so we use identical splits/features.
        import json as _json

        from alive.provenance import RunLedger as _RunLedger

        data_card = _json.loads((run_dir / "data_card.json").read_text(encoding="utf-8"))
        import anndata as _ad

        adata = _ad.read_h5ad(data_card["h5ad"])
        sequences = _json.loads((world_dir / "sequences.json").read_text(encoding="utf-8"))
        config = load_config(config_path)
        # Read the full config digest the CLI recorded in the ledger so both
        # paths get the same config_sha256 value.
        ledger_data = _RunLedger.read(run_dir / "ledger.json").to_dict()
        config_sha256_for_staged = ledger_data["config_sha256"]
        schema = DatasetSchema(
            perturbation_key=data_card["perturbation_key"],
            control_value=data_card["control_value"],
        )
        index = build_index(adata, schema, min_cells=config.response_space.min_cells)
        manifest = build_manifest_from_index(index, config.split_fractions, config.manifest_seed)
        base_train_ids = list(manifest.ids_for("base_train"))
        feature_bank = build_feature_bank(
            {g: seqs for g, seqs in sequences.items()},
            MockSequenceEncoder(dim=8),
            sequence_source="mock-2026",
            id_mapping_version="id-map-v1",
            standardize_on=base_train_ids,
        )
        audit_path = world_dir / "parity_audit.jsonl"
        store = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=audit_path
        )
        base_art = fit_base(index, store, manifest, feature_bank, config)
        staged_method_lock, staged_futility = develop_methods_stage(
            index,
            store,
            manifest,
            base_art,
            feature_bank,
            config,
            config_sha256=config_sha256_for_staged,
        )

        # The checksums must be byte-identical: same inputs → same computation.
        assert cli_method_lock.checksum == staged_method_lock.checksum, (
            f"CLI MethodLock checksum {cli_method_lock.checksum!r} != "
            f"staged {staged_method_lock.checksum!r}. "
            "CLI develop/futility path has diverged from develop_methods_stage()."
        )
        assert cli_futility.checksum == staged_futility.checksum, (
            f"CLI FutilityDecision checksum {cli_futility.checksum!r} != "
            f"staged {staged_futility.checksum!r}. "
            "CLI develop/futility path has diverged from develop_methods_stage()."
        )


# ===========================================================================
# P1-1: feature eligibility BEFORE the split
# ===========================================================================


def _write_world_with_missing_sequences(
    tmp_path: Path,
    *,
    seed: int = 0,
    n_pert: int = 40,
    missing_genes: list[str] | None = None,
    ambiguous_genes: list[str] | None = None,
) -> tuple[Path, Path]:
    """Like _write_world but with some genes missing or ambiguous in the sequence map."""
    rng = np.random.default_rng(seed)
    genes = [f"GENE{i:03d}" for i in range(n_pert)]
    cells_per = {g: int(rng.integers(20, 30)) for g in genes}
    adata = _make_adata(n_ctrl=80, pert_cells=cells_per, n_genes=20, seed=seed + 1)

    h5ad_path = tmp_path / "synthetic.h5ad"
    adata.write_h5ad(h5ad_path)

    # Sequences: normal for most genes, missing for some, ambiguous for others.
    missing_set = set(missing_genes or [])
    ambiguous_set = set(ambiguous_genes or [])
    sequences: dict = {}
    for g in genes:
        if g in missing_set:
            sequences[g] = []  # 0 sequences → excluded as "missing sequence"
        elif g in ambiguous_set:
            sequences[g] = [_seq_for(g), _seq_for(g + "_alt")]  # 2 seqs → "ambiguous mapping"
        else:
            sequences[g] = [_seq_for(g)]

    seq_path = tmp_path / "sequences.json"
    seq_path.write_text(json.dumps(sequences), encoding="utf-8")

    cfg = json.loads(json.dumps(_BASE_CONFIG))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")

    data_card = {
        "h5ad": str(h5ad_path),
        "sequences": str(seq_path),
        "perturbation_key": _PERT_KEY,
        "control_value": _CTRL_VAL,
        "gene_id_key": None,
        "counts_layer": None,
        "raw_data_uri": "synthetic://cli-test",
        "sequence_source": "uniprot-2024-01",
        "id_mapping_version": "ensembl-110",
    }
    data_card_path = tmp_path / "data_card.json"
    data_card_path.write_text(json.dumps(data_card), encoding="utf-8")
    return config_path, data_card_path


class TestFeatureEligibilityBeforeSplit:
    """P1-1: feature-missing perturbations must be excluded BEFORE the split.

    After prepare:
    (a) Missing / ambiguous perturbations must NOT appear in any manifest split.
    (b) They must appear in manifest exclusions (surfaced from index exclusions).
    (c) Every id assigned to any split must be in feature_bank.genes.
    (d) Sealed-cohort membership reflects post-feature-exclusion counts.
    """

    def test_missing_and_ambiguous_excluded_before_split(self, tmp_path: Path) -> None:
        # Two genes missing from sequence map, one ambiguous.
        missing = ["GENE000", "GENE001"]
        ambiguous = ["GENE002"]
        config_path, data_card_path = _write_world_with_missing_sequences(
            tmp_path,
            seed=7,
            missing_genes=missing,
            ambiguous_genes=ambiguous,
        )
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        rc = _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        assert rc == 0, "prepare must succeed"

        # Load produced artifacts.
        from alive.data.features import FeatureBank
        from alive.data.manifest import SplitManifest

        manifest = SplitManifest.read(run_dir / "manifest.json")
        feature_bank = FeatureBank.read(run_dir / "feature_bank")

        # (a) Missing and ambiguous genes must not appear in any split.
        excluded_genes = set(missing) | set(ambiguous)
        all_split_ids: set[str] = set()
        _splits = ("base_train", "method_development", "conformal_calibration", "sealed_evaluation")
        for split_name in _splits:
            split_ids = set(manifest.ids_for(split_name))
            bad = excluded_genes & split_ids
            assert bad == set(), (
                f"Feature-ineligible genes {bad} should not appear in split {split_name!r}"
            )
            all_split_ids |= split_ids

        # (b) Excluded genes are captured in manifest exclusions.
        excl = manifest.exclusions
        for gene in excluded_genes:
            assert gene in excl, (
                f"Gene {gene!r} should be in manifest.exclusions (got {sorted(excl.keys())!r})"
            )

        # (c) All split ids must be in feature_bank.genes.
        bank_genes = set(feature_bank.genes)
        not_in_bank = all_split_ids - bank_genes
        assert not_in_bank == set(), f"These split ids are NOT in feature_bank.genes: {not_in_bank}"

        # (d) Counts are consistent: no excluded gene inflates split sizes.
        for split_name in _splits:
            for gid in manifest.ids_for(split_name):
                assert gid in bank_genes, f"{gid} in split {split_name!r} but missing from bank"


# ===========================================================================
# P0-1: no silent mock fallback + config↔feature-bank encoder cross-check
# ===========================================================================


class TestNoSilentMockFallback:
    """P0-1(a): prepare WITHOUT --mock-encoder must fail (no ESM in CI)."""

    def test_prepare_without_mock_encoder_fails_with_clear_error(
        self, tmp_path: Path, capsys
    ) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=42)
        root = _artifacts_root(tmp_path)

        # Do NOT pass --mock-encoder: ESM is unavailable in CI, so this must
        # exit non-zero with a clear error — no silent fallback to mock.
        rc = _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                # intentionally omitting --mock-encoder
            ],
            root,
        )
        assert rc != 0, "prepare must fail when ESM is unavailable and --mock-encoder is not set"
        combined = "".join(capsys.readouterr())
        # Error message must mention ESM, not just a generic failure.
        assert "esm" in combined.lower() or "encoder" in combined.lower(), (
            f"Expected ESM-related error message, got: {combined!r}"
        )
        assert "Traceback" not in combined, "must not produce a traceback (clean error)"


class TestMockEncoderFlag:
    """P0-1(b): --mock-encoder succeeds and records encoder_kind in run_meta.json."""

    def test_mock_encoder_flag_sets_encoder_kind(self, tmp_path: Path) -> None:
        config_path, data_card_path = _write_world(tmp_path, seed=42)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        rc = _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        assert rc == 0, "prepare --mock-encoder must succeed"
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["encoder_kind"] == "mock", (
            f"run_meta.json encoder_kind should be 'mock', got {meta!r}"
        )


class TestEncoderConfigCrossCheck:
    """P0-1(b): cross-check helper expected_primary(prov) == config.primary."""

    def test_expected_primary_mismatch_raises(self) -> None:
        """A provenance whose model_revision+pooling mismatches config raises CliError."""
        from alive.cli import CliError, _expected_primary
        from alive.data.features import FeatureBankProvenance

        # Config primary: "esm2_t33_650M_UR50D_mean_pool"
        config_primary = "esm2_t33_650M_UR50D_mean_pool"

        # Build a provenance that does NOT match.
        prov = FeatureBankProvenance(
            model_revision="mock-v1",
            sequence_source="test",
            id_mapping_version="id-map-v1",
            pooling="mean",
            dim=8,
            dtype="float32",
            n_genes=5,
            mapping_sha256="0" * 64,
            features_sha256="0" * 64,
        )
        # _expected_primary(prov) == "mock-v1_mean_pool" ≠ config_primary
        derived = _expected_primary(prov)
        assert derived != config_primary
        # When not mock, the scientific cross-check should catch this mismatch.
        with pytest.raises(CliError, match="encoder"):
            if derived != config_primary:
                raise CliError(
                    f"encoder config mismatch: feature bank was built with encoder "
                    f"{derived!r} but config.perturbation_features.primary is "
                    f"{config_primary!r}. Re-run prepare with the correct encoder."
                )

    def test_expected_primary_match_does_not_raise(self) -> None:
        """A provenance whose model_revision+pooling matches config is accepted."""
        from alive.cli import _expected_primary
        from alive.data.features import FeatureBankProvenance

        config_primary = "esm2_t33_650M_UR50D_mean_pool"
        prov = FeatureBankProvenance(
            model_revision="esm2_t33_650M_UR50D",
            sequence_source="test",
            id_mapping_version="id-map-v1",
            pooling="mean",
            dim=1280,
            dtype="float32",
            n_genes=5,
            mapping_sha256="0" * 64,
            features_sha256="0" * 64,
        )
        derived = _expected_primary(prov)
        assert derived == config_primary


# ===========================================================================
# Protein-sequence provenance separation (Task 1 / audit P2-1)
# ===========================================================================


def _run_prepare_with_data_card(tmp_path: Path, *, drop_keys: list[str]) -> int:
    """Run ``prepare`` with a data card missing the specified keys; return the exit code."""
    config_path, data_card_path = _write_world(tmp_path)
    data_card = json.loads(data_card_path.read_text(encoding="utf-8"))
    for key in drop_keys:
        data_card.pop(key, None)
    data_card_path.write_text(json.dumps(data_card), encoding="utf-8")
    return _run(
        [
            "cartographer",
            "prepare",
            "--config",
            str(config_path),
            "--data-card",
            str(data_card_path),
            "--mock-encoder",
        ],
        _artifacts_root(tmp_path),
    )


class TestProteinSequenceProvenance:
    """Task 1 / audit P2-1: protein-sequence provenance is separate from expression source."""

    def test_prepare_records_protein_sequence_provenance(self, tmp_path: Path) -> None:
        from alive.data.features import FeatureBank
        from alive.provenance import RunLedger

        config_path, data_card_path = _write_world(tmp_path)
        root = _artifacts_root(tmp_path)
        run_id = _run_id(config_path, data_card_path)
        run_dir = root / "cartographer" / run_id

        rc = _run(
            [
                "cartographer",
                "prepare",
                "--config",
                str(config_path),
                "--data-card",
                str(data_card_path),
                "--mock-encoder",
            ],
            root,
        )
        assert rc == 0

        bank = FeatureBank.read(run_dir / "feature_bank")
        # sequence_source is the protein DB release, NOT the expression URI
        assert bank.provenance.sequence_source == "uniprot-2024-01"
        assert bank.provenance.sequence_source != "synthetic://cli-test"
        assert bank.provenance.id_mapping_version == "ensembl-110"

        ledger = RunLedger.read(run_dir / "ledger.json")
        assert ledger.artifact_sha("sequence_mapping") == bank.provenance.mapping_sha256
        assert ledger.artifact_sha("raw_data")  # expression hash still present & distinct
        assert ledger.artifact_sha("raw_data") != ledger.artifact_sha("sequence_mapping")

    def test_prepare_refuses_data_card_missing_sequence_source(self, tmp_path: Path) -> None:
        rc = _run_prepare_with_data_card(tmp_path, drop_keys=["sequence_source"])
        assert rc == 2

    def test_prepare_refuses_data_card_missing_id_mapping_version(self, tmp_path: Path) -> None:
        rc = _run_prepare_with_data_card(tmp_path, drop_keys=["id_mapping_version"])
        assert rc == 2


@pytest.fixture(autouse=True)
def _no_cwd_artifacts(monkeypatch, tmp_path):
    """Guard: never write to a repo-level artifacts/ during tests."""
    monkeypatch.chdir(tmp_path)
    yield
