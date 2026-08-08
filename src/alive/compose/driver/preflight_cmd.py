"""``preflight`` subcommand orchestration (COMPOSE production driver, spec §3.2).

The ``preflight`` subcommand is the independent pre-seal gate that runs AFTER
``phase2a`` (spec §1 canonical order ``phase2a → preflight → phase2b``): the
library ``run_preflight`` validates the FROZEN prediction bundle, so it is only
meaningful once ``phase2a`` has produced that bundle. This subcommand follows the
§1 four-step shape — verify entry state, read only the permitted pre-built
artifacts, assemble the in-memory objects, then call the library entry point and
persist its output write-once — WITHOUT re-implementing any science:

1. assert the ``preflight`` run-directory ENTRY roster (§7.1) FIRST — the four
   phase2a artifacts required; confirmation / terminal / audit / pre-access /
   durable files forbidden — so a stray seal-adjacent artifact fails closed
   before any gate work;
2. load + validate the immutable ResolvedRunSpec, load the frozen bundle via
   :meth:`~alive.compose.freeze.FrozenPredictionBundle.load`, and — the load-
   bearing rule (§1) — RE-READ the persisted phase2a ledger via
   :meth:`~alive.provenance.RunLedger.read`. The ledger is NEVER reconstructed
   from the bundle: doing so would make preflight's ledger↔bundle checksum check
   a tautology;
3. call the outcome-free :func:`~alive.compose.preflight.run_preflight` gate,
   which returns a frozen :class:`~alive.compose.preflight.EvaluationLock` or
   fails closed with :class:`~alive.compose.preflight.PreflightError`;
4. on success, build the FULL §3.2 ``compose_seal_confirmation_manifest_v1`` and
   install it write-once as ``seal_confirmation_manifest.json``.

Seal safety (§4). This subcommand constructs **no**
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` of any kind, imports no
``gears`` / ``cpa`` (the ``worker_identity`` is assembled from re-hashed
worker/adapter file digests only), and opens no seal — the sealed store's single
creation point is ``phase2b`` alone.

Manifest population (§3.2). Every field is sourced deterministically from the
EvaluationLock + the re-read ledger + the ResolvedRunSpec + the config, so a
separate ``phase2b`` process (Task 9/13) reconstructing from the CURRENT
non-sealed state reproduces the manifest byte-for-byte:

* ``ordered_seal_request_checksum`` is computed with the EXACT phase2b
  ``intent_checksum`` expression (phase2b.py:1269-1277) — a byte divergence
  would make phase2b's confirmation reconstruction fail;
* ``method_roster`` / ``comparator_roster`` are the config2 constants (the
  confirmation builder references them; never hardcoded here);
* ``worker_identity`` is the canonical 6-field ``ExecutionIdentityLock`` mapping
  per method for exactly ``{gears, cpa}`` (assembled via Task 4 from re-hashed
  real bytes; :func:`dataclasses.asdict`).

Exit codes (§1.1): ``0`` = pre-seal gate passed + manifest installed; ``10`` =
pre-seal validation rejected (no seal consumed, no manifest installed).

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §3.2.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from alive.compose.config2 import ComposePhase2Config, load_compose_phase2_config
from alive.compose.driver.confirmation import (
    build_seal_confirmation_manifest,
    install_seal_confirmation_manifest,
)
from alive.compose.driver.identity_lock import (
    DEEP_BASELINE_METHODS,
    assemble_execution_identity_lock,
)
from alive.compose.driver.pair_index import validate_pair_index_manifest_preseal
from alive.compose.driver.phase2a_cmd import (
    LEDGER_EXECUTION_ID,
    LEDGER_PAIR_INDEX_MANIFEST,
    LEDGER_RESOLVED_RUN_SPEC,
    LEDGER_SEED_REPORT,
)
from alive.compose.driver.run_dir_state import assert_run_dir_roster
from alive.compose.driver.run_spec import (
    RUN_PRODUCED_BASENAMES,
    ResolvedRunSpec,
    compute_execution_id,
    load_resolved_run_spec,
)
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.preflight import EvaluationLock, PreflightError, run_preflight
from alive.provenance import LedgerError, RunLedger, sha256_file, sha256_json

__all__ = [
    "PREFLIGHT_PASS_EXIT",
    "PREFLIGHT_REJECT_EXIT",
    "ACCEPTED_LIMITATIONS",
    "PreflightSubcommandError",
    "build_confirmation_inputs",
    "run_preflight_subcommand",
]

#: Exit code for a passed pre-seal gate with the confirmation manifest installed.
PREFLIGHT_PASS_EXIT = 0

#: Exit code for a pre-seal validation rejection (no seal consumed, no manifest).
PREFLIGHT_REJECT_EXIT = 10

#: The owner-approved ``accepted_limitations`` roster bound into the confirmation
#: manifest (spec §3.2 / §9). Sourced deterministically HERE so a separate
#: phase2b process reconstructs the identical roster. This records the gene-
#: sharing pair-bootstrap dependency as an explicit accepted limitation (spec §9:
#: the primary analysis is retained; this is a non-verdict sensitivity note).
#: NOTE (scientific follow-up): a scientific ResolvedRunSpec should carry the
#: owner-approved roster explicitly (a PREPARE obligation); the fixture path uses
#: this committed constant.
ACCEPTED_LIMITATIONS: tuple[str, ...] = (
    "Pair-bootstrap resampling treats evaluation pairs as independent; gene sharing "
    "across evaluation pairs may weaken the coverage of independent pair resampling. "
    "Retained as the primary analysis with an explicit non-verdict accepted limitation "
    "(spec §9).",
)


class PreflightSubcommandError(RuntimeError):
    """Raised on a driver-level preflight orchestration failure (fail-closed).

    Distinct from :class:`~alive.compose.preflight.PreflightError` (the library
    pre-seal gate, mapped to exit ``10``). Covers a re-read ledger that does not
    bind the loaded ResolvedRunSpec (a wrong-ledger / tampered-driver-artifact
    integrity failure), a worker-block roster that is not exactly ``{gears, cpa}``,
    and a scientific carrier lacking a resolved ``git_is_clean`` flag.
    """


# --------------------------------------------------------------------------- #
# Public subcommand
# --------------------------------------------------------------------------- #


def run_preflight_subcommand(
    run_spec: Any,
    *,
    approved_artifacts_root: str | Path,
    run_dir: str | Path,
) -> int:
    """Run the pre-seal gate and install the §3.2 confirmation manifest.

    Parameters
    ----------
    run_spec
        The stage-1 DATA carrier (locally the committed fixture builder's
        :class:`~alive.compose.driver.fixture_builder.FixtureBundle`) carrying the
        canonical ResolvedRunSpec path (``spec_path``) and the LIVE response
        artifact (``response_artifact`` — the source of the independent
        ``expected_response_dim`` the gate cross-checks against the frozen
        bundle). No sealed store is ever built from it here.
    approved_artifacts_root
        The out-of-band CLI trust root; its canonical realpath must equal the
        ResolvedRunSpec's declared ``approved_artifacts_root``.
    run_dir
        The shared run directory. Must hold EXACTLY the four phase2a artifacts at
        entry (§7.1); the confirmation manifest is the only new install.

    Returns
    -------
    int
        ``0`` on a passed gate with the manifest installed; ``10`` on a pre-seal
        rejection (no seal consumed, no manifest installed).

    Raises
    ------
    RunDirStateError
        If the preflight entry roster is violated (checked BEFORE any gate work) —
        e.g. a forbidden terminal/confirmation present, or a required phase2a
        artifact (including the ledger) missing.
    RunSpecError
        If the ResolvedRunSpec fails validation.
    LedgerError
        If the persisted ledger is unreadable / malformed.
    PreflightSubcommandError
        On a ledger↔spec binding failure or a malformed worker roster.
    """
    run_dir = Path(run_dir)

    # Step 1: run-directory ENTRY roster FIRST (the 4 phase2a artifacts required;
    # confirmation/terminal/audit/pre-access/durable forbidden). A missing ledger
    # or a stray seal-adjacent artifact fails closed here, before any gate work.
    assert_run_dir_roster(run_dir, "preflight")

    # Step 2: load + validate the immutable ResolvedRunSpec (trust boundary),
    # load the frozen bundle, and RE-READ the persisted ledger (NO reconstruction
    # from the bundle — §1). The re-read ledger is what run_preflight's ledger↔
    # bundle checksum check consumes, so that check is not a tautology.
    spec_path = Path(run_spec.spec_path)
    mode = _peek_mode(spec_path)
    spec = load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected=mode
    )
    bundle = FrozenPredictionBundle.load(run_dir / RUN_PRODUCED_BASENAMES["frozen_bundle"])
    ledger_path = run_dir / RUN_PRODUCED_BASENAMES["run_ledger"]
    ledger = RunLedger.read(ledger_path)

    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    pair_manifest = _load_pair_manifest(spec)
    expected_response_dim = _expected_response_dim(run_spec)

    # Cross-check the re-read ledger's driver-added artifacts against the loaded
    # ResolvedRunSpec (spec §1/§3.2: after re-reading, bind artifact SHAs to the
    # ResolvedRunSpec). A ledger vouching for a different spec fails closed.
    _assert_ledger_binds_spec(ledger, spec)

    # Step 2c: pre-seal pair-index manifest validation + attestation binding
    # (spec §2.3 / Task 2). Verify the pair_index_manifest v1 schema + self-
    # checksum and its binding to the approved_sealed_input_attestation (source-
    # file SHA + obs row-identity SHA equality) over the already-SHA-verified
    # pre-seal bytes — WITHOUT opening the sealed source (the semantic obs-
    # alignment check is phase2b step 5's post-claim validator).
    # A violation raises RunSpecError → the CLI's pre-seal exit 10 (no seal armed).
    manifest_bytes = Path(spec.pre_seal["pair_index_manifest"].path).read_bytes()
    attestation_bytes = Path(spec.pre_seal["approved_sealed_input_attestation"].path).read_bytes()
    validate_pair_index_manifest_preseal(
        json.loads(manifest_bytes),
        attestation=json.loads(attestation_bytes),
        pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
    )

    # Step 3: the outcome-free pre-seal gate. A rejection returns 10 (no seal
    # consumed, no manifest installed); it builds no store of any kind.
    try:
        lock = run_preflight(
            bundle=bundle,
            pair_manifest=pair_manifest,
            config=config,
            data_card_digest=spec.data_card_digest,
            raw_or_source_digest=spec.raw_or_source_digest,
            sequence_mapping_digest=spec.sequence_mapping_digest,
            ledger=ledger,
            expected_response_dim=expected_response_dim,
        )
    except PreflightError:
        return PREFLIGHT_REJECT_EXIT

    # Step 4: build the FULL §3.2 confirmation manifest + install write-once.
    git_clean = _resolve_git_clean(spec, run_spec)
    inputs = build_confirmation_inputs(
        spec=spec,
        config=config,
        ledger=ledger,
        ledger_path=ledger_path,
        lock=lock,
        bundle=bundle,
        git_clean=git_clean,
    )
    manifest = build_seal_confirmation_manifest(**inputs)
    install_seal_confirmation_manifest(
        run_dir / RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"], manifest
    )
    return PREFLIGHT_PASS_EXIT


# --------------------------------------------------------------------------- #
# §3.2 manifest input assembly (shared with phase2b's Task-9/13 reconstruction)
# --------------------------------------------------------------------------- #


def build_confirmation_inputs(
    *,
    spec: ResolvedRunSpec,
    config: ComposePhase2Config,
    ledger: RunLedger,
    ledger_path: str | Path,
    lock: EvaluationLock,
    bundle: FrozenPredictionBundle,
    git_clean: bool,
) -> dict[str, Any]:
    """Assemble the 15 keyword inputs :func:`build_seal_confirmation_manifest` consumes.

    Every value is sourced deterministically from the EvaluationLock + the re-read
    ledger + the ResolvedRunSpec + the config, so a separate ``phase2b`` process
    reconstructing from the CURRENT non-sealed state (Task 9/13) reproduces the
    manifest byte-for-byte. This helper is intentionally public so phase2b's
    confirmation reconstruction calls the SAME code — never a divergent copy.

    Parameters
    ----------
    spec
        The validated, immutable ResolvedRunSpec (run/execution identity, the
        pre-seal ``feature_bank`` file SHA, the worker blocks).
    config
        The validated Phase-2 config (the config identity and the selected
        hyperparameters mapping; the confirmation builder pulls the two rosters
        from config2 itself).
    ledger
        The re-read phase2a ledger (the ``data_card`` / ``sequence_mapping`` /
        ``pair_index_manifest`` / ``phase2a_seed_variability_report`` artifact
        SHAs).
    ledger_path
        The ledger file's path; its byte SHA is the manifest's ``ledger_checksum``.
    lock
        The frozen :class:`~alive.compose.preflight.EvaluationLock` (the
        bundle/manifest/response-space/factor/model checksums, the run id, the
        per-regime sealed pair sets).
    bundle
        The re-read :class:`~alive.compose.freeze.FrozenPredictionBundle`; supplies
        the SELECTED hyperparameter point (``selected_k_total`` /
        ``selected_lambda``) bound into the manifest's ``selected_hyperparameters``.
        Both callers (preflight install and phase2b reconstruction) already load
        the identical bundle, so this stays byte-reproducible.
    git_clean
        The resolved clean-git flag (True in fixture mode; the scientific carrier
        value otherwise).

    Returns
    -------
    dict
        The exact keyword arguments for :func:`build_seal_confirmation_manifest`.
    """
    execution_id = compute_execution_id(
        run_id=lock.run_id,
        resolved_run_spec_file_sha256=spec.file_sha256,
        approved_git_sha=spec.approved_git_sha,
    )
    return {
        "run_id": lock.run_id,
        "execution_id": execution_id,
        "resolved_run_spec_file_sha256": spec.file_sha256,
        "approved_git_sha": spec.approved_git_sha,
        "git_clean": bool(git_clean),
        "preseal_checksums": _preseal_checksums(
            spec=spec, config=config, ledger=ledger, ledger_path=ledger_path, lock=lock
        ),
        "selected_hyperparameters": _selected_hyperparameters(config, bundle),
        "worker_identity": _worker_identity(spec, config),
        "double_pair_count": len(lock.pair_ids_double_unseen),
        "single_pair_count": len(lock.pair_ids_single_unseen),
        "ordered_seal_request_checksum": _ordered_seal_request_checksum(lock),
        "futility_status": "CONTINUE",
        "sealed_access_count": 0,
        "forbidden_output_absence": True,
        "accepted_limitations": list(ACCEPTED_LIMITATIONS),
    }


def _preseal_checksums(
    *,
    spec: ResolvedRunSpec,
    config: ComposePhase2Config,
    ledger: RunLedger,
    ledger_path: str | Path,
    lock: EvaluationLock,
) -> dict[str, str]:
    """The COMPLETE 12-key §3.2 pre-seal content-checksum set.

    Sources (all deterministic + reproducible in a separate phase2b process):

    * ``config``            → the config's own identity (``config.config_sha256``);
    * ``data_card`` /
      ``sequence``          → the re-read ledger artifact SHAs;
    * ``manifest`` / ``factor`` /
      ``response_space`` / ``model`` /
      ``bundle``            → the verified EvaluationLock checksums;
    * ``feature``           → the ResolvedRunSpec's verified ``feature_bank`` file SHA
                              (there is no feature-bank ledger artifact / expected-
                              hashes key; the pre-seal file SHA is the deterministic
                              source);
    * ``ledger``            → the persisted ledger file's own byte SHA;
    * ``pair_index`` /
      ``seed_report``       → the driver-added ledger artifact SHAs (phase2a).
    """
    return {
        "config_checksum": config.config_sha256,
        "data_card_checksum": _ledger_artifact(ledger, "data_card"),
        "manifest_checksum": lock.manifest_checksum,
        "sequence_checksum": _ledger_artifact(ledger, "sequence_mapping"),
        "feature_checksum": spec.pre_seal["feature_bank"].sha256,
        "factor_checksum": lock.factor_checksum,
        "response_space_checksum": lock.response_space_checksum,
        "model_checksum": lock.model_checksum,
        "bundle_checksum": lock.bundle_checksum,
        "ledger_checksum": sha256_file(ledger_path),
        "pair_index_checksum": _ledger_artifact(ledger, LEDGER_PAIR_INDEX_MANIFEST),
        "seed_report_checksum": _ledger_artifact(ledger, LEDGER_SEED_REPORT),
    }


def _selected_hyperparameters(
    config: ComposePhase2Config, bundle: FrozenPredictionBundle
) -> dict[str, Any]:
    """The registered search space AND the SELECTED point, deterministically bound.

    COMPOSE pre-registers the identifiable-operator search space and the
    selection-controlling knobs in the committed config, and the frozen prediction
    bundle records the point actually selected by the dev-OOF procedure
    (``selected_k_total`` / ``selected_lambda``). The confirmation manifest's
    ``selected_hyperparameters`` binds BOTH — the search configuration (what was
    searched) and the selected point (what is being sealed) — so the manifest
    self-describes the sealed hyperparameters, not only the grid. Both are
    deterministic and reproducible in a separate phase2b process: the selected
    point is read from the SAME frozen bundle in the bundle's canonical
    ``round(., 12)`` lambda representation (freeze.py), avoiding any dependence on
    fit-time float state.
    """
    return {
        "total_k_grid": [int(k) for k in config.total_k_grid],
        "lambda_grid": [float(x) for x in config.lambda_grid],
        "unregularized_solver": str(config.unregularized_solver),
        "regularized_solver": str(config.regularized_solver),
        "unregularized_oof_rank_policy": str(config.unregularized_oof_rank_policy),
        "rank_tolerance_rule": str(config.rank_tolerance_rule),
        "oof_folds": int(config.oof_folds),
        "split_seed": int(config.split_seed),
        "registered_seeds": [int(s) for s in config.registered_seeds],
        "uncovered_tolerance": float(config.uncovered_tolerance),
        # Load-bearing beside `total_k_grid`: the conditioning screen removes
        # CANDIDATES before scoring -- a whole `k_total` at every lambda when the
        # full design is over the bound, or that `k_total`'s `lam=0.0` candidate
        # alone when only a train fold is. Recording the grid without the bound that
        # filtered it would misdescribe what was actually searched. "dimensions" was
        # the k_total/candidate conflation this protocol registers as a
        # misattribution.
        "condition_ceiling": float(config.condition_ceiling),
        "dev_oof_metric": str(config.dev_oof_metric),
        "dev_oof_threshold": float(config.dev_oof_threshold),
        "selected_k_total": int(bundle.selected_k_total),
        "selected_lambda": round(float(bundle.selected_lambda), 12),
    }


def _worker_identity(spec: ResolvedRunSpec, config: ComposePhase2Config) -> dict[str, Any]:
    """Per-method ``{gears, cpa}`` 6-field ``ExecutionIdentityLock`` identity.

    The canonical form (spec §3.2): the FULL 6-field lock mapping per method,
    assembled via the Task-4 assembler from the ResolvedRunSpec worker blocks
    (re-hashed real worker/adapter bytes) — deterministic and identical to what
    the runtime verifies the worker self-report against. Imports no ``gears`` /
    ``cpa``: the lock is identity digests only.
    """
    methods = set(spec.worker_blocks)
    if methods != set(DEEP_BASELINE_METHODS):
        raise PreflightSubcommandError(
            f"worker blocks must be exactly {{'gears', 'cpa'}} for the worker "
            f"identity, got {sorted(methods)}"
        )
    representations = {name: rep for name, rep, _bias in config.baseline_representations}
    identity: dict[str, Any] = {}
    for method, block in spec.worker_blocks.items():
        representation = representations.get(method)
        if not isinstance(representation, str) or not representation:
            raise PreflightSubcommandError(
                f"no config representation registered for method {method!r}"
            )
        lock = assemble_execution_identity_lock(
            block,
            config_representation=representation,
            fixture=(spec.mode == "fixture"),
            expected_worker_method=method,
        )
        identity[method] = dataclasses.asdict(lock)
    return identity


def _ordered_seal_request_checksum(lock: EvaluationLock) -> str:
    """The ordered seal-request intent checksum (byte-identical to phase2b).

    This is the EXACT phase2b ``intent_checksum`` expression (phase2b.py:1269-
    1277): §3.2 says "ordered", but the committed phase2b sorts the pair lists, so
    the manifest matches the CODE. A byte divergence here would make phase2b's
    confirmation reconstruction fail closed.
    """
    return sha256_json(
        {
            "run_id": lock.run_id,
            "bundle_checksum": lock.bundle_checksum,
            "manifest_checksum": lock.manifest_checksum,
            "double_pairs": sorted(list(p) for p in lock.pair_ids_double_unseen),
            "single_pairs": sorted(list(p) for p in lock.pair_ids_single_unseen),
        }
    )


# --------------------------------------------------------------------------- #
# Assembly helpers
# --------------------------------------------------------------------------- #


def _peek_mode(spec_path: Path) -> str:
    """Read the declared ``mode`` before the full load (loader re-validates it)."""
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PreflightSubcommandError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in {"fixture", "scientific"}:
        raise PreflightSubcommandError(f"ResolvedRunSpec declares an unrecognised mode {mode!r}")
    return mode


def _load_pair_manifest(spec: ResolvedRunSpec) -> dict[str, Any]:
    """Load the pre-seal pair (split) manifest JSON (roles + self-checksum).

    A plain JSON read of the ResolvedRunSpec's verified ``pair_manifest`` path
    (the loader already matched its declared SHA to the on-disk bytes). This is a
    digest-only pre-seal read: no AnnData / backed access / row materialization.
    """
    path = Path(spec.pre_seal["pair_manifest"].path)
    try:
        manifest = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PreflightSubcommandError(f"cannot read pair manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PreflightSubcommandError("pair manifest must be a JSON object")
    return manifest


def _expected_response_dim(run_spec: Any) -> int:
    """The independent expected response dimension the gate cross-checks.

    Sourced from the carrier's live response space (``response_space.pca_dim``) —
    the SAME source phase2b uses (phase2b.py:1190). It is an independent property
    of the response space that ``run_preflight`` cross-checks against the frozen
    bundle's ``response_dim``, so passing it is not a tautology.
    """
    try:
        response_space = run_spec.response_artifact["response_space"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise PreflightSubcommandError(
            "run_spec carrier is missing the live response artifact needed for "
            "the expected response dimension"
        ) from exc
    return int(response_space.pca_dim)


def _assert_ledger_binds_spec(ledger: RunLedger, spec: ResolvedRunSpec) -> None:
    """Cross-check the re-read ledger's driver-added artifacts bind THIS spec.

    ``run_preflight`` binds the ledger's identity header + upstream artifacts to
    the bundle. This adds the driver's own binding (spec §1/§3.2): the ledger's
    ``resolved_run_spec`` file SHA, ``execution_id`` and ``pair_index_manifest``
    SHA must equal the values re-derived from the loaded ResolvedRunSpec — a
    ledger recorded under a DIFFERENT spec (wrong-ledger / driver-artifact tamper)
    fails closed here rather than silently sealing a mismatched confirmation.
    """
    execution_id = compute_execution_id(
        run_id=spec.run_id,
        resolved_run_spec_file_sha256=spec.file_sha256,
        approved_git_sha=spec.approved_git_sha,
    )
    expected = {
        LEDGER_RESOLVED_RUN_SPEC: spec.file_sha256,
        LEDGER_EXECUTION_ID: execution_id,
        LEDGER_PAIR_INDEX_MANIFEST: spec.pre_seal["pair_index_manifest"].sha256,
    }
    for name, want in expected.items():
        got = _ledger_artifact(ledger, name)
        if got != want:
            raise PreflightSubcommandError(
                f"re-read ledger artifact {name!r} ({got!r}) does not bind the loaded "
                f"ResolvedRunSpec (expected {want!r}); wrong or tampered ledger"
            )


def _resolve_git_clean(spec: ResolvedRunSpec, run_spec: Any) -> bool:
    """Resolve the clean-git flag for the confirmation manifest.

    Fixture mode has no real Git working tree (``approved_git_sha`` is a fixed
    placeholder), so the deterministic fixture value is ``True``. Scientific mode
    takes the carrier's verified ``git_is_clean`` (the same flag the scientific
    ``phase2a`` dispatch consumes) and fails closed if it is absent — a scientific
    confirmation must never silently attest a clean tree.
    """
    if spec.mode == "fixture":
        return True
    git_is_clean = getattr(run_spec, "git_is_clean", None)
    if not isinstance(git_is_clean, bool):
        raise PreflightSubcommandError(
            "scientific preflight requires a boolean git_is_clean from the run_spec carrier"
        )
    return git_is_clean


def _ledger_artifact(ledger: RunLedger, name: str) -> str:
    """Return ``ledger.artifact_sha(name)``, re-raising a miss as a fail-closed error."""
    try:
        return ledger.artifact_sha(name)
    except LedgerError as exc:
        raise PreflightSubcommandError(
            f"re-read ledger is missing required artifact {name!r}: {exc}"
        ) from exc
