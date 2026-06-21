"""Reproducible CLI runner for the CARTOGRAPHER Trust-Gate MVP (Task 17).

Exposes the ``alive cartographer`` subcommand group, one subcommand per staged
function in :mod:`alive.experiment.real_runner`, each persisting/loading its
artifact(s) from ``artifacts/cartographer/<run_id>/``.  The ``run_id`` is the
composite immutable identifier (:func:`alive.provenance.compute_run_id`) binding
the config to the data card, raw expression file, and protein-sequence mapping.

Subcommands::

    alive cartographer prepare      --config <yaml> --data-card <json>
    alive cartographer fit          --run-id <run_id>
    alive cartographer develop      --run-id <run_id>
    alive cartographer futility     --run-id <run_id>
    alive cartographer calibrate    --run-id <run_id>
    alive cartographer evaluate-once --run-id <run_id>
    alive cartographer report       --run-id <run_id>

Integrity properties enforced here:

- ``evaluate-once`` REFUSES (non-zero exit) unless the persisted
  :class:`~alive.experiment.develop.FutilityDecision` status is
  ``CONTINUE_CONFIRMATORY``; the seal never opens otherwise.
- ``calibrate`` runs in EITHER branch (a futility-stopped run still ships its
  conformal artifact).
- ``report`` NEVER recomputes; it reads persisted artifacts only.
- The ``RunLedger`` records the FULL config digest (``sha256_file`` of the
  config) and every artifact checksum, so the provenance leg of the integrity
  gate genuinely fires in ``evaluate-once``.

The real K562 run executes on the A100; here the CLI is exercised on SYNTHETIC
data only.  The encoder is selected by the CLI: the real ESM-2 encoder when the
optional ``features`` deps are importable, otherwise the numpy-only
:class:`~alive.data.features.MockSequenceEncoder`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from alive.config import ConfigError, load_config
from alive.conformal.error_bound import ConformalArtifact, ConformalError
from alive.data.features import (
    FeatureError,
    MockSequenceEncoder,
    build_feature_bank,
    canonical_mapping_sha256,
)
from alive.data.manifest import ManifestError, SplitManifest, build_manifest_from_index
from alive.data.outcome_store import ReplogleOutcomeStore, SealingError
from alive.data.preprocess import PreprocessError, ResponseSpace
from alive.data.replogle import DatasetSchema, build_index
from alive.eval import report as report_mod
from alive.experiment.develop import (
    DevelopError,
    FutilityDecision,
    MethodLock,
    decide_futility,
    develop_methods,
)
from alive.experiment.real_runner import (
    BaseArtifact,
    calibrate,
    evaluate_sealed_once,
    fit_base,
    perturbation_inputs,
)
from alive.metrics.selective import normalize_by_mean
from alive.provenance import (
    LedgerError,
    RunLedger,
    capture_environment,
    compute_run_id,
    sha256_file,
    sha256_json,
)
from alive.types import OperationalStatus

# ---------------------------------------------------------------------------
# Artifact layout
# ---------------------------------------------------------------------------

_DEFAULT_ARTIFACTS_ROOT = "artifacts"


class CliError(RuntimeError):
    """Raised for clean, user-facing CLI failures (printed without traceback)."""


#: Exception types that ``main`` surfaces as a clean one-line error (exit 2)
#: rather than a traceback: explicit CLI refusals, missing artifacts, the Task-5
#: once-only seal guard, and the tamper-detected artifact checksum / schema
#: errors raised by the per-artifact ``.read`` methods.  This list is precise on
#: purpose so genuine programming bugs still surface as tracebacks.
_CLEAN_ERRORS: tuple[type[BaseException], ...] = (
    CliError,
    FileNotFoundError,
    SealingError,
    report_mod.ReportError,
    ConfigError,
    ConformalError,
    DevelopError,
    FeatureError,
    ManifestError,
    PreprocessError,
    LedgerError,
)


def _run_dir(artifacts_root: Path, run_id: str) -> Path:
    return Path(artifacts_root) / "cartographer" / run_id


def _require_run_dir(artifacts_root: Path, run_id: str) -> Path:
    rd = _run_dir(artifacts_root, run_id)
    if not rd.exists():
        raise CliError(
            f"run-id {run_id!r} not found under {artifacts_root / 'cartographer'}. "
            "Run `alive cartographer prepare` first."
        )
    return rd


def _base_paths(run_dir: Path) -> tuple[Path, Path]:
    """Return the (response_space, base_predictor) base paths (no extension)."""
    return run_dir / "base", run_dir / "base_predictor"


# ---------------------------------------------------------------------------
# Encoder selection
# ---------------------------------------------------------------------------


def _expected_primary(provenance: "object") -> str:
    """Derive the expected config ``perturbation_features.primary`` string from provenance.

    The canonical mapping is: ``f"{prov.model_revision}_{prov.pooling}_pool"``.

    Parameters
    ----------
    provenance : FeatureBankProvenance
        The provenance record of a built :class:`~alive.data.features.FeatureBank`.

    Returns
    -------
    str
        The expected ``primary`` config string.
    """
    return f"{provenance.model_revision}_{provenance.pooling}_pool"


def _select_encoder(*, use_mock: bool, config_primary: str = "", config=None):
    """Return the encoder to use.

    Parameters
    ----------
    use_mock : bool
        If ``True``, return the :class:`~alive.data.features.MockSequenceEncoder`
        (numpy-only, safe for CI).  If ``False``, attempt to import ESM-2; on
        ANY failure raise :class:`CliError` with a clear message — **no silent
        fallback**.
    config_primary : str, optional
        The ``config.perturbation_features.primary`` string; included in the error
        message when ESM is unavailable.
    config : Config or None, optional
        Full experiment config.  When provided, ``config.feature_extraction``
        fields are forwarded to the scientific :class:`~alive.data.features.Esm2Encoder`.
        When ``None``, encoder defaults are used.
    """
    if use_mock:
        return MockSequenceEncoder(dim=8)

    try:
        import esm  # noqa: F401, PLC0415
        import torch  # noqa: F401, PLC0415

        from alive.data.features import Esm2Encoder

        if config is not None:
            fe = config.feature_extraction
            return Esm2Encoder(
                max_residues=fe.max_residues,
                long_sequence_policy=fe.long_sequence_policy,
                max_batch_tokens=fe.max_batch_tokens,
            )
        return Esm2Encoder()
    except Exception as exc:  # noqa: BLE001
        raise CliError(
            f"ESM encoder is required (config primary {config_primary!r}) but is unavailable: "
            f"{exc}. Pass --mock-encoder only for synthetic/CI runs."
        ) from exc


# ---------------------------------------------------------------------------
# Shared loaders
# ---------------------------------------------------------------------------


def _load_world(run_dir: Path):
    """Reconstruct (index, store, manifest, feature_bank, config) from artifacts."""
    data_card = json.loads((run_dir / "data_card.json").read_text(encoding="utf-8"))
    config = load_config(run_dir / "config.snapshot.yaml")

    schema = DatasetSchema(
        perturbation_key=data_card["perturbation_key"],
        control_value=data_card["control_value"],
        gene_id_key=data_card.get("gene_id_key"),
        counts_layer=data_card.get("counts_layer"),
    )
    h5ad = data_card["h5ad"]
    index = build_index(h5ad, schema, min_cells=config.response_space.min_cells)
    manifest = SplitManifest.read(run_dir / "manifest.json")
    from alive.data.features import FeatureBank

    feature_bank = FeatureBank.read(run_dir / "feature_bank")
    store = ReplogleOutcomeStore(
        index=index, source=h5ad, manifest=manifest, audit_path=run_dir / "audit.jsonl"
    )
    return index, store, manifest, feature_bank, config


def _load_base_artifact(run_dir: Path) -> BaseArtifact:
    rs_path, pred_path = _base_paths(run_dir)
    from alive.base.predictor import BasePredictor

    rs = ResponseSpace.read(rs_path)
    pred = BasePredictor.read(pred_path)
    return BaseArtifact(response_space=rs, base_predictor=pred)


def _config_digest(config_source: Path) -> str:
    """Full config digest (carry-forward fix c): sha256 of the config file."""
    return sha256_file(config_source)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def usable_feature_genes(gene_sequences: dict) -> set:
    """Return the set of gene IDs with exactly one sequence (usable by the feature bank).

    Parameters
    ----------
    gene_sequences : dict
        Mapping from gene ID to a list of candidate protein sequences.
        Genes with zero sequences are missing; genes with >1 are ambiguous.
        Both are ineligible and excluded from the returned set.

    Returns
    -------
    set[str]
        Gene IDs that have exactly one candidate sequence.
    """
    return {g for g, seqs in gene_sequences.items() if len(seqs) == 1}


def cmd_prepare(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    data_card_path = Path(args.data_card)
    config = load_config(config_path)

    data_card = json.loads(data_card_path.read_text(encoding="utf-8"))

    # Require protein-sequence provenance keys (separate from expression source).
    for required in ("sequence_source", "id_mapping_version"):
        if required not in data_card:
            raise CliError(
                f"data card is missing required key {required!r} (protein-sequence "
                "provenance must be declared separately from the expression source)."
            )

    # P1-1 FIX: load sequences FIRST so feature eligibility is determined BEFORE
    # building the index/manifest.  This ensures excluded perturbations (missing or
    # ambiguous sequences) never enter any split.
    sequences = json.loads(Path(data_card["sequences"]).read_text(encoding="utf-8"))
    gene_sequences = {g: list(seqs) for g, seqs in sequences.items()}
    usable_gene_ids = usable_feature_genes(gene_sequences)

    # #4 / P1-2: derive the COMPOSITE immutable run_id BEFORE creating the run
    # directory.  Binding the config to the exact data, raw expression file, and
    # protein-sequence mapping means the same config on different data yields a
    # different run directory (spec §11.2).  ``raw_data_sha256`` is computed once
    # here and reused for the ``raw_data`` ledger artifact (no double-hash).
    h5ad = data_card["h5ad"]
    config_digest = config.config_digest
    data_card_digest = sha256_json(data_card)
    raw_data_sha256 = _raw_data_hash(h5ad, data_card)
    sequence_mapping_sha256 = canonical_mapping_sha256(gene_sequences)
    run_id = compute_run_id(
        config_digest, data_card_digest, raw_data_sha256, sequence_mapping_sha256
    )

    run_dir = _run_dir(Path(args.artifacts_root), run_id)
    if run_dir.exists():
        raise CliError(
            f"run directory for run-id {run_id!r} already exists at {run_dir}. "
            "Runs are immutable; prepare refuses to overwrite. Remove it deliberately "
            "or change the config/data to start a new run."
        )
    run_dir.mkdir(parents=True, exist_ok=False)

    # Snapshot the config + data card under the run dir (immutable inputs).
    (run_dir / "config.snapshot.yaml").write_text(
        config_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (run_dir / "data_card.json").write_text(
        json.dumps(data_card, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    schema = DatasetSchema(
        perturbation_key=data_card["perturbation_key"],
        control_value=data_card["control_value"],
        gene_id_key=data_card.get("gene_id_key"),
        counts_layer=data_card.get("counts_layer"),
    )
    # Pass usable_gene_ids so build_index excludes feature-missing perturbations
    # and records them in index.exclusions with reason "no external feature".
    index = build_index(
        h5ad,
        schema,
        min_cells=config.response_space.min_cells,
        available_feature_ids=usable_gene_ids,
    )
    manifest = build_manifest_from_index(index, config.split_fractions, config.manifest_seed)
    manifest.write(run_dir / "manifest.json")

    base_train_ids = list(manifest.ids_for("base_train"))
    encoder = _select_encoder(
        use_mock=args.mock_encoder,
        config_primary=config.perturbation_features.primary,
        config=config,
    )
    feature_bank = build_feature_bank(
        gene_sequences,
        encoder,
        sequence_source=data_card["sequence_source"],
        id_mapping_version=data_card["id_mapping_version"],
        standardize_on=base_train_ids,
    )
    feature_bank.write(run_dir / "feature_bank")

    # P1-1 HARD ASSERTION: every perturbation in any manifest split must be in
    # feature_bank.genes.  A violation indicates a logic error in the ordering.
    bank_genes: set[str] = set(feature_bank.genes)
    offending: list[str] = []
    _all_splits = ("base_train", "method_development", "conformal_calibration", "sealed_evaluation")
    for split_name in _all_splits:
        for pid in manifest.ids_for(split_name):
            if pid not in bank_genes:
                offending.append(pid)
    if offending:
        raise CliError(
            f"Manifest/feature-bank agreement violation: {len(offending)} perturbation(s) "
            f"assigned to a split are not in the feature bank — this is a logic error. "
            f"Offending IDs: {sorted(offending)[:10]}{'...' if len(offending) > 10 else ''}"
        )

    # P0-1: record encoder kind and (if scientific) cross-check config ↔ feature bank.
    encoder_kind = "mock" if args.mock_encoder else "scientific"
    if not args.mock_encoder:
        derived = _expected_primary(feature_bank.provenance)
        if derived != config.perturbation_features.primary:
            raise CliError(
                f"encoder config mismatch: feature bank was built with encoder "
                f"{derived!r} but config.perturbation_features.primary is "
                f"{config.perturbation_features.primary!r}. "
                "Re-run prepare with the correct encoder."
            )

    # Record the run_id alongside artifacts (config snapshot has no run_id).
    # encoder_kind is recorded so evaluate-once can pass require_encoder_match.
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {"run_id": run_id, "experiment": config.experiment, "encoder_kind": encoder_kind}
        ),
        encoding="utf-8",
    )

    # Initialise the durable RunLedger with the FULL config digest (fix c) and
    # record the immutable input hashes (config, raw data, manifest, feature bank).
    config_sha256 = _config_digest(config_path)
    environment = capture_environment(
        _lockfile_for(config_path), config.method_development.registered_seeds
    )
    ledger = RunLedger(run_id=run_id, config_sha256=config_sha256, environment=environment)
    ledger.record_artifact("config", config_sha256)
    # Reuse the raw_data hash computed for the composite run_id (no double-hash).
    ledger.record_artifact("raw_data", raw_data_sha256)
    # sequence_mapping_sha256 == feature_bank.provenance.mapping_sha256 by
    # construction (canonical_mapping_sha256 is the shared helper).
    ledger.record_artifact("sequence_mapping", sequence_mapping_sha256)
    ledger.record_artifact("split_manifest", manifest.checksum)
    ledger.record_artifact("feature_bank", feature_bank.checksum)
    ledger.write(run_dir / "ledger.json")

    print(run_id)
    return 0


def _lockfile_for(config_path: Path) -> Path:
    """Best-effort lockfile for environment capture (uv.lock if present)."""
    for parent in [config_path.resolve().parent, *config_path.resolve().parents]:
        candidate = parent / "uv.lock"
        if candidate.exists():
            return candidate
    # Fall back to the config file itself so capture_environment never crashes.
    return config_path


def _raw_data_hash(h5ad: str, data_card: dict) -> str:
    """Hash the raw data file if local; else fall back to the declared URI hash."""
    path = Path(h5ad)
    if path.exists():
        return sha256_file(path)
    return sha256_json({"raw_data_uri": data_card.get("raw_data_uri", h5ad)})


def cmd_fit(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    index, store, manifest, feature_bank, config = _load_world(run_dir)

    base_artifact = fit_base(index, store, manifest, feature_bank, config)
    rs_path, pred_path = _base_paths(run_dir)
    base_artifact.response_space.write(rs_path)
    base_artifact.base_predictor.write(pred_path)

    _ledger_record(run_dir, "base_artifact", base_artifact.checksum)
    return 0


def cmd_develop(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    index, store, manifest, feature_bank, config = _load_world(run_dir)
    base_artifact = _load_base_artifact(run_dir)
    config_sha256 = _ledger_config_sha(run_dir)

    # Compute the method_development inputs ONCE (read_unsealed only — no seal).
    # Seed the equal-cell sampling of the shared method_development reference bank
    # with the COMPOSITE run_id (spec §4.5) — the SAME value evaluate-once uses —
    # so the gate/comparator scorers refitted at sealed evaluation are byte-
    # identical to those fitted here (NOT the config digest, which would diverge).
    dev_ids_all = [pid for pid in manifest.ids_for("method_development") if feature_bank.has(pid)]
    populations = store.read_unsealed(dev_ids_all)
    ids, features, errors, ensemble_means = perturbation_inputs(
        base_artifact.base_predictor,
        base_artifact.response_space,
        feature_bank,
        populations,
        response_cfg=config.response_space,
        run_id=args.run_id,
    )

    md = config.method_development
    method_lock = develop_methods(
        ids,
        features,
        errors,
        ensemble_means,
        cv_folds=md.cv_folds,
        k_grid=md.k_grid,
        feature_weight_grid=md.feature_weight_grid,
        ridge_grid=md.ridge_grid,
        gbm_estimators_grid=md.gbm_estimators_grid,
        registered_seeds=md.registered_seeds,
        config_sha256=config_sha256,
    )
    method_lock.write(run_dir / "methodlock")

    # Persist dev (ids, errors) so `futility` decides without re-opening data.
    np.savez_compressed(
        run_dir / "dev_errors.npz",
        **{report_mod.DEV_IDS_KEY: np.asarray(ids), report_mod.DEV_ERRORS_KEY: errors},
    )

    _ledger_record(run_dir, "method_lock", method_lock.checksum)
    return 0


def cmd_futility(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    _index, _store, _manifest, _fb, config = _load_world(run_dir)
    config_sha256 = _ledger_config_sha(run_dir)

    method_lock = MethodLock.read(run_dir / "methodlock")
    _ids, errors = report_mod.load_dev_errors(run_dir)
    norm_errors = normalize_by_mean(errors)

    futility = decide_futility(
        method_lock,
        norm_errors,
        comparators=config.futility.comparators,
        delta_min=config.futility.minimum_relevant_delta,
        confidence=config.futility.family_confidence,
        n_replicates=config.inference.bootstrap_replicates,
        seed=config.manifest_seed,
        config_sha256=config_sha256,
    )
    futility.write(run_dir / "futility.json")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    index, store, manifest, feature_bank, config = _load_world(run_dir)
    base_artifact = _load_base_artifact(run_dir)
    method_lock = MethodLock.read(run_dir / "methodlock")
    config_sha256 = _ledger_config_sha(run_dir)

    # calibrate RUNS IN EITHER BRANCH (a futility-stopped run still ships its
    # conformal artifact); the futility decision is intentionally not consulted.
    # Seed the shared method_development reference-bank sampling with the COMPOSITE
    # run_id (spec §4.5) — the SAME value evaluate-once uses — so the gate scorer
    # fitted here matches the one refitted at sealed evaluation (the conformal
    # threshold and the sealed scores compared against it must come from one
    # identically-fitted model).
    conformal = calibrate(
        index,
        store,
        manifest,
        base_artifact,
        method_lock,
        feature_bank,
        config,
        run_id=args.run_id,
        config_sha256=config_sha256,
    )
    conformal.write(run_dir / "conformal.json")

    _ledger_record(run_dir, "conformal_artifact", conformal.checksum)
    return 0


def cmd_evaluate_once(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    index, store, manifest, feature_bank, config = _load_world(run_dir)
    base_artifact = _load_base_artifact(run_dir)
    method_lock = MethodLock.read(run_dir / "methodlock")
    conformal = ConformalArtifact.read(run_dir / "conformal.json")
    futility = FutilityDecision.read(run_dir / "futility.json")

    # REFUSE unless CONTINUE_CONFIRMATORY (the seal must never open otherwise).
    if futility.status != OperationalStatus.CONTINUE_CONFIRMATORY:
        raise CliError(
            f"evaluate-once refused: futility status is {futility.status.value!r}, "
            "not CONTINUE_CONFIRMATORY. The sealed cohort stays shut. "
            "A futility-stopped run still ships its conformal artifact and a "
            "futility report; run `alive cartographer report` instead."
        )

    ledger = RunLedger.read(run_dir / "ledger.json")
    config_sha256 = _ledger_config_sha(run_dir)

    # Determine encoder_kind from run_meta.json (written by prepare).
    # Older runs without the field default to "mock" for backward compatibility.
    run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    encoder_kind = run_meta.get("encoder_kind", "mock")

    result = evaluate_sealed_once(
        index,
        store,
        manifest,
        base_artifact,
        method_lock,
        conformal,
        futility,
        feature_bank,
        config,
        # The actual run identity is the composite run_id (= the run directory
        # name the user passes), NOT the config digest.  Result provenance, the
        # sealed-access audit, and deterministic seed-keys must all carry it.
        run_id=args.run_id,
        config_sha256=config_sha256,
        ledger=ledger,
        result_path=run_dir / "result.json",
        require_encoder_match=(encoder_kind == "scientific"),
    )
    ledger.write(run_dir / "ledger.json")
    print(result.verdict.value)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = _require_run_dir(Path(args.artifacts_root), args.run_id)
    report = report_mod.build_report(run_dir)
    print(json.dumps({"mode": report["mode"], "run_dir": str(run_dir)}))
    return 0


# ---------------------------------------------------------------------------
# Ledger update helpers
# ---------------------------------------------------------------------------


def _ledger_config_sha(run_dir: Path) -> str:
    ledger = RunLedger.read(run_dir / "ledger.json")
    return ledger.to_dict()["config_sha256"]


def _ledger_record(run_dir: Path, name: str, checksum: str) -> None:
    """Record (or refresh) an artifact checksum in the on-disk ledger.

    Re-records idempotently: if *name* is already present with a DIFFERENT hash,
    the entry is replaced (a stage may be re-run); the write-once ledger is
    rebuilt from its dict to honour that without mutating in place.
    """
    ledger = RunLedger.read(run_dir / "ledger.json")
    data = ledger.to_dict()
    artifacts = [a for a in data["artifacts"] if a["name"] != name]
    artifacts.append({"name": name, "sha256": checksum})
    data["artifacts"] = artifacts
    (run_dir / "ledger.json").write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alive", description="ALIVE CARTOGRAPHER CLI runner.")
    parser.add_argument(
        "--artifacts-root",
        default=_DEFAULT_ARTIFACTS_ROOT,
        help="Root directory for run artifacts (default: ./artifacts).",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    cart = sub.add_parser("cartographer", help="Trust-Gate MVP staged runner.")
    cart_sub = cart.add_subparsers(dest="command", required=True)

    p_prepare = cart_sub.add_parser("prepare", help="Build manifest + feature bank + ledger.")
    p_prepare.add_argument("--config", required=True)
    p_prepare.add_argument("--data-card", required=True)
    p_prepare.add_argument(
        "--mock-encoder",
        action="store_true",
        default=False,
        help=(
            "Use the numpy-only MockSequenceEncoder instead of ESM-2. "
            "ONLY for synthetic/CI runs — the real A100 run must use the scientific encoder."
        ),
    )
    p_prepare.set_defaults(func=cmd_prepare)

    for name, func, helptext in (
        ("fit", cmd_fit, "Fit response space + base predictor."),
        ("develop", cmd_develop, "Develop methods (MethodLock + dev_errors)."),
        ("futility", cmd_futility, "Compute the futility decision."),
        ("calibrate", cmd_calibrate, "Build the conformal artifact (either branch)."),
        ("evaluate-once", cmd_evaluate_once, "The single audited sealed evaluation."),
        ("report", cmd_report, "Emit the locked report for the terminal state."),
    ):
        p = cart_sub.add_parser(name, help=helptext)
        p.add_argument("--run-id", required=True)
        p.set_defaults(func=func)

    return parser


def _hoist_artifacts_root(argv_list: list[str]) -> list[str]:
    """Move any ``--artifacts-root <value>`` token pair to the front of *argv_list*."""
    root_val: str | None = None
    cleaned: list[str] = []
    i = 0
    while i < len(argv_list):
        tok = argv_list[i]
        if tok == "--artifacts-root" and i + 1 < len(argv_list):
            root_val = argv_list[i + 1]
            i += 2
            continue
        if tok.startswith("--artifacts-root="):
            root_val = tok.split("=", 1)[1]
            i += 1
            continue
        cleaned.append(tok)
        i += 1
    if root_val is not None:
        return ["--artifacts-root", root_val, *cleaned]
    return cleaned


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parameters
    ----------
    argv : list[str] or None, optional
        Argument vector (excluding the program name).  ``None`` uses
        :data:`sys.argv`.

    Returns
    -------
    int
        Process exit code (0 on success, non-zero on a clean CLI error).
    """
    parser = _build_parser()
    # The top-level ``--artifacts-root`` option may be written anywhere on the
    # command line (including after the subcommand, where users naturally place
    # it).  argparse only accepts a top-level optional BEFORE the subcommand, so
    # pull it to the front here.
    argv_list = list(argv if argv is not None else sys.argv[1:])
    front = _hoist_artifacts_root(argv_list)
    args = parser.parse_args(front)

    try:
        return int(args.func(args))
    except _CLEAN_ERRORS as exc:
        # Expected, user-facing failures (refusals, missing artifacts, the
        # once-only seal guard, tamper-detected checksums): a clear one-line
        # message, never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
