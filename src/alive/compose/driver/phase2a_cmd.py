"""``phase2a`` subcommand orchestration (COMPOSE production driver, spec §3.1).

The first real driver subcommand. It follows the §1 four-step shape — verify the
ResolvedRunSpec, read only the permitted pre-built artifacts, assemble the
in-memory objects, then call the library entry point and persist its outputs
write-once — WITHOUT re-implementing any science:

1. assert the ``phase2a`` run-directory ENTRY roster (§7.1) BEFORE anything else,
   so a partially populated ``run_dir`` fails closed before any fit;
2. load + fully validate the immutable ResolvedRunSpec (the driver trust
   boundary, :func:`~alive.compose.driver.run_spec.load_resolved_run_spec`);
3. assemble the typed :class:`~alive.compose.phase2a.Phase2aInputs`, a non-sealed
   :class:`~alive.compose.phase2a.DevelopmentOutcomeStore`, and the ``{gears,
   cpa}`` subprocess :class:`~alive.compose.baselines_combo.BaselineAdapter`s
   whose 6-field ``ExecutionIdentityLock`` is assembled from re-hashed real bytes
   (§5, Task 4);
4. dispatch the correct library entry point
   (``run_phase2a_fixture`` / ``run_phase2a``), and on ``CONTINUE`` run the D2
   development seed-variability harness on the FROZEN OOF, then install exactly
   the four pre-seal artifacts write-once with the run ledger LAST.

The fixture/scientific asymmetry the driver resolves (§3.1): scientific
``run_phase2a`` takes ``activation_record`` / ``git_is_clean`` /
``data_card_path`` / ``raw_asset_path`` / ``response_artifact`` explicitly, while
``run_phase2a_fixture`` relies on the ``Phase2aInputs``' embedded
``response_space_checksum`` and has NO ``response_artifact`` argument.

Seal safety (§4). This subcommand constructs **no**
:class:`~alive.compose.outcome_store.ComposeOutcomeStore`, imports no
``gears`` / ``cpa``, and opens no seal — the sealed store's single creation point
is ``phase2b`` alone. The seed-variability report is written to the DISTINCT
``phase2a_development_seed_variability.json`` (NOT the canonical
``development_seed_variability.json`` that ``phase2b``'s
``bind_development_seed_variability`` write-once installs — a same-name write
would collide across the shared ``run_dir``).

Exit codes (§1.1): ``0`` = phase2a CONTINUE persisted; ``20`` = FUTILITY_STOPPED
(a valid stop; phase2b forbidden).

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §3.1.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from alive.compose.baselines_combo import BaselineAdapter
from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver.identity_lock import assemble_baseline_backends
from alive.compose.driver.run_dir_state import assert_run_dir_roster
from alive.compose.driver.run_spec import (
    RUN_PRODUCED_BASENAMES,
    ResolvedRunSpec,
    compute_execution_id,
    load_resolved_run_spec,
)
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    Phase2aInputs,
    Phase2aResult,
    build_subprocess_fit_payload,
    run_phase2a,
    run_phase2a_fixture,
)
from alive.compose.seed_variability import development_seed_variability
from alive.io import atomic_write_once
from alive.provenance import RunLedger, sha256_file, sha256_json

__all__ = [
    "CONTINUE_EXIT",
    "FUTILITY_EXIT",
    "FUTILITY_REPORT_SCHEMA",
    "LEDGER_RESOLVED_RUN_SPEC",
    "LEDGER_EXECUTION_ID",
    "LEDGER_PAIR_INDEX_MANIFEST",
    "LEDGER_SEED_REPORT",
    "Phase2aSubcommandError",
    "run_phase2a_subcommand",
]

#: Exit code for a persisted phase2a CONTINUE (spec §1.1).
CONTINUE_EXIT = 0

#: Exit code for a FUTILITY_STOPPED phase2a (a valid stop; phase2b forbidden).
FUTILITY_EXIT = 20

#: Exact ``schema`` discriminator of the write-once futility report (spec §3.1).
FUTILITY_REPORT_SCHEMA = "compose_phase2a_futility_v2"

#: Canonical ledger artifact names for the four driver-added SHAs (spec §3.1).
#: These extend — and are distinct from — the artifacts the Phase-2a orchestrator
#: already records, and are the shared ledger artifact-name contract the C0
#: preflight-leg fix reads (spec §0.1 "Code-fix 범위 정리").
LEDGER_RESOLVED_RUN_SPEC = "resolved_run_spec"
LEDGER_EXECUTION_ID = "execution_id"
LEDGER_PAIR_INDEX_MANIFEST = "pair_index_manifest"
LEDGER_SEED_REPORT = "phase2a_seed_variability_report"


class Phase2aSubcommandError(RuntimeError):
    """Raised on a driver-level phase2a orchestration failure (fail-closed).

    Distinct from the library entry point's own errors (hash / leakage /
    scientific-mode). Covers an unexpected futility status and a run-ledger
    snapshot that fails post-install byte verification.
    """


# --------------------------------------------------------------------------- #
# Public subcommand
# --------------------------------------------------------------------------- #


def run_phase2a_subcommand(
    run_spec: Any,
    *,
    approved_artifacts_root: str | Path,
    run_dir: str | Path,
) -> int:
    """Assemble, dispatch and persist one ``phase2a`` run (spec §3.1).

    Parameters
    ----------
    run_spec
        The stage-1 DATA carrier the driver assembles from. Locally this is the
        committed fixture builder's
        :class:`~alive.compose.driver.fixture_builder.FixtureBundle`, which
        carries the canonical fixture ResolvedRunSpec path (``spec_path``), the
        typed in-memory ``Phase2aInputs`` (``phase2a_inputs``), the non-sealed
        dev-store DATA (``dev_store_audit``), and the LIVE response artifact
        (``response_artifact`` — there is no ``ResponseSpace.load``, so the live
        objects are carried, not re-hydrated from disk).
    approved_artifacts_root
        The out-of-band CLI trust root; its canonical realpath must equal the
        ResolvedRunSpec's declared ``approved_artifacts_root``.
    run_dir
        The run directory the four pre-seal artifacts are installed into. Must be
        a direct child of the approved root and hold no run-produced artifact at
        entry (§7.1).

    Returns
    -------
    int
        ``0`` on a persisted CONTINUE; ``20`` on FUTILITY_STOPPED.

    Raises
    ------
    RunDirStateError
        If the run-directory entry roster is violated (checked BEFORE any fit).
    RunSpecError
        If the ResolvedRunSpec fails validation.
    Phase2aSubcommandError
        On an unexpected futility status or a ledger post-install mismatch.
    """
    run_dir = Path(run_dir)

    # Step 1: run-directory ENTRY roster — nothing run-produced may exist yet.
    assert_run_dir_roster(run_dir, "phase2a")

    # Step 2: load + validate the immutable ResolvedRunSpec (trust boundary).
    spec_path = Path(run_spec.spec_path)
    mode = _peek_mode(spec_path)
    spec = load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected=mode
    )

    # Step 3: assemble the in-memory objects (inputs / dev store / adapters).
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    inputs: Phase2aInputs = run_spec.phase2a_inputs
    dev_store = _build_development_store(run_spec)
    response_artifact = run_spec.response_artifact
    payload_response = {
        "response_space": response_artifact["response_space"],
        "control_mean": response_artifact["control_mean"],
    }
    adapters = _assemble_adapters(
        spec, config=config, inputs=inputs, dev_store=dev_store, response_artifact=response_artifact
    )

    # Step 4: dispatch the correct entry point (fixture/scientific asymmetry).
    bundle_path = run_dir / RUN_PRODUCED_BASENAMES["frozen_bundle"]
    oof_manifest_path = run_dir / RUN_PRODUCED_BASENAMES["oof_manifest"]
    if spec.mode == "fixture":
        result = run_phase2a_fixture(
            inputs,
            dev_store,
            expected_hashes=dict(spec.expected_hashes),
            config=config,
            bundle_path=bundle_path,
            baseline_adapters=adapters,
            oof_manifest_path=oof_manifest_path,
        )
    else:
        # Scientific dispatch: run_phase2a additionally verifies the activation
        # record, clean git, on-disk data-card/raw asset and the response
        # artifact (which — unlike the payload projection — must ALSO carry its
        # own ``checksum``). The scientific run-spec carrier supplies these; the
        # committed FixtureBundle is fixture-only, so this branch is not reached
        # in the local fixture path (full scientific carrier wiring is a T8/PREPARE
        # obligation).
        scientific_response = {
            **payload_response,
            "checksum": response_artifact["combined_checksum"],
        }
        result = run_phase2a(
            inputs,
            dev_store,
            expected_hashes=dict(spec.expected_hashes),
            config=config,
            bundle_path=bundle_path,
            baseline_adapters=adapters,
            oof_manifest_path=oof_manifest_path,
            environment=run_spec.environment,
            activation_record=run_spec.activation_record,
            git_is_clean=run_spec.git_is_clean,
            data_card_path=run_spec.data_card_path,
            raw_asset_path=run_spec.raw_asset_path,
            response_artifact=scientific_response,
        )

    # Step 4 (cont.): persist per the futility status.
    if result.futility_status == "FUTILITY_STOPPED":
        return _persist_futility_report(run_dir, run_id=spec.run_id, result=result)
    if result.futility_status == "CONTINUE":
        return _persist_continue(
            run_dir,
            spec=spec,
            config=config,
            inputs=inputs,
            dev_store=dev_store,
            adapters=adapters,
            response_artifact=response_artifact,
            result=result,
        )
    raise Phase2aSubcommandError(f"unexpected phase2a futility status {result.futility_status!r}")


# --------------------------------------------------------------------------- #
# Assembly helpers
# --------------------------------------------------------------------------- #


def _peek_mode(spec_path: Path) -> str:
    """Read the declared ``mode`` before the full load (loader re-validates it)."""
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Phase2aSubcommandError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in {"fixture", "scientific"}:
        raise Phase2aSubcommandError(f"ResolvedRunSpec declares an unrecognised mode {mode!r}")
    return mode


def _build_development_store(run_spec: Any) -> DevelopmentOutcomeStore:
    """Construct the non-sealed dev store FROM the carrier's dev-store DATA (§3.1)."""
    audit = run_spec.dev_store_audit
    return DevelopmentOutcomeStore(
        combo_calibration_eps=audit["combo_calibration_eps"],
        combo_calibration_pair_ids=audit["combo_calibration_pair_ids"],
        access_audit=audit["access_audit"],
    )


def _assemble_adapters(
    spec: ResolvedRunSpec,
    *,
    config,
    inputs: Phase2aInputs,
    dev_store: DevelopmentOutcomeStore,
    response_artifact: Mapping[str, Any],
) -> dict[str, BaselineAdapter]:
    """Assemble the ``{gears, cpa}`` subprocess adapters (spec §3.1 / §5).

    Each adapter is a ``SubprocessBaselineBackend`` carrying its driver-assembled
    ``ExecutionIdentityLock`` (built from re-hashed real worker/adapter bytes),
    configured with the single combined-fit payload, then wrapped in a
    ``BaselineAdapter``. Supplying exactly ``{gears, cpa}`` is what actually
    exercises the lock-assembler + worker-manifest verification path
    (``_validate_baseline_adapters`` accepts them iff exactly this set).
    """
    representations = {name: rep for name, rep, _bias in config.baseline_representations}
    backends = assemble_baseline_backends(
        spec,
        fixture=(spec.mode == "fixture"),
        representations=representations,
        seed=int(inputs.seed),
    )
    payload = build_subprocess_fit_payload(
        inputs=inputs,
        outcome_store=dev_store,
        response_artifact={
            "response_space": response_artifact["response_space"],
            "control_mean": response_artifact["control_mean"],
        },
        # The main combined-fit fold labels are payload metadata; the D2 harness
        # re-derives its own per-fold labels from the verified OOF manifest.
        oof_folds=[0] * len(inputs.cal_pair_ids),
        fit_role_spec=response_artifact["fit_role_spec"],
        gene_order=response_artifact["gene_order"],
        raw_data_sha256=response_artifact["raw_data_sha256"],
    )
    adapters: dict[str, BaselineAdapter] = {}
    for name, backend in backends.items():
        backend.configure_payload(payload)
        adapters[name] = BaselineAdapter(name=name, backend=backend)
    return adapters


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _persist_continue(
    run_dir: Path,
    *,
    spec: ResolvedRunSpec,
    config,
    inputs: Phase2aInputs,
    dev_store: DevelopmentOutcomeStore,
    adapters: Mapping[str, BaselineAdapter],
    response_artifact: Mapping[str, Any],
    result: Phase2aResult,
) -> int:
    """Persist the four CONTINUE artifacts write-once, run ledger LAST (§3.1).

    The entry point already wrote the frozen bundle (via ``bundle_path=``) and the
    OOF manifest (via ``oof_manifest_path=``). Here we run the D2 seed-variability
    harness on the FROZEN OOF and write it to the DISTINCT path, then record the
    four driver-added SHAs into the in-memory ledger and install the ledger LAST —
    so the preflight that reads the ledger sees every pre-seal artifact bound.
    """
    oof_manifest = result.oof_manifest
    ledger = result.ledger
    if oof_manifest is None or ledger is None:
        raise Phase2aSubcommandError(
            "CONTINUE result is missing its frozen OOF manifest or run ledger"
        )

    # D2: development seed-variability on the frozen OOF (orchestration only).
    report = development_seed_variability(
        inputs=inputs,
        development_outcome_store=dev_store,
        oof_manifest=oof_manifest,
        baseline_adapters=dict(adapters),
        config=config,
        response_artifact={
            "response_space": response_artifact["response_space"],
            "control_mean": response_artifact["control_mean"],
        },
        fit_role_spec=response_artifact["fit_role_spec"],
        gene_order=response_artifact["gene_order"],
        raw_data_sha256=response_artifact["raw_data_sha256"],
    )
    seed_report_path = run_dir / RUN_PRODUCED_BASENAMES["phase2a_seed_variability_report"]
    report.write_once(seed_report_path)  # DISTINCT path (never the canonical name)
    seed_report_sha = sha256_file(seed_report_path)

    # Record the four driver-added artifact SHAs into the in-memory ledger.
    execution_id = compute_execution_id(
        run_id=spec.run_id,
        resolved_run_spec_file_sha256=spec.file_sha256,
        approved_git_sha=spec.approved_git_sha,
    )
    ledger.record_artifact(LEDGER_RESOLVED_RUN_SPEC, spec.file_sha256)
    ledger.record_artifact(LEDGER_EXECUTION_ID, execution_id)
    ledger.record_artifact(LEDGER_PAIR_INDEX_MANIFEST, spec.pre_seal["pair_index_manifest"].sha256)
    ledger.record_artifact(LEDGER_SEED_REPORT, seed_report_sha)

    # Install the run ledger LAST (canonical bytes, atomic write-once, re-read).
    _install_run_ledger(run_dir / RUN_PRODUCED_BASENAMES["run_ledger"], ledger)

    # Self-check: exactly the four CONTINUE artifacts now present (§7.1).
    assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="CONTINUE")
    return CONTINUE_EXIT


def _install_run_ledger(path: Path, ledger: RunLedger) -> None:
    """Atomically install the ledger canonical bytes and verify the re-read.

    Reuses the ``persist_pre_access_ledger`` pattern (spec §0.1 #2): NOT
    ``RunLedger.write`` (a plain overwrite), but ``atomic_write_once`` over the
    canonical bytes followed by a ``RunLedger.read`` equality check, so a stale
    or racing ledger cannot be silently clobbered.
    """
    text = json.dumps(ledger.to_dict(), sort_keys=True, separators=(",", ":"))
    try:
        atomic_write_once(path, text)
    except FileExistsError as exc:
        raise Phase2aSubcommandError(
            f"phase2a run ledger already exists at {str(path)!r}; the lifecycle is write-once"
        ) from exc
    installed = RunLedger.read(path)
    if installed != ledger:
        raise Phase2aSubcommandError("phase2a run ledger snapshot failed post-install verification")


def _persist_futility_report(run_dir: Path, *, run_id: str, result: Phase2aResult) -> int:
    """Write ONLY the write-once futility report and return 20 (spec §3.1 / §7.1).

    No bundle / ledger / seal artifacts. The report is a self-checksummed,
    OUTCOME-FREE development diagnostic (rank / conditioning / measurability /
    selected hyperparameters + the zero sealed-access count) — never a verdict.
    """
    futility = result.futility
    rank = futility.rank_report
    condition_number = float(rank.condition_number)
    body = {
        "schema": FUTILITY_REPORT_SCHEMA,
        "run_id": run_id,
        "futility_status": result.futility_status,
        "sealed_access_count": int(result.sealed_access_count),
        "selected_k_total": int(result.selected_k_total),
        "selected_lambda": round(float(result.selected_lambda), 12),
        "rank": int(rank.rank),
        "sym_dim": int(rank.sym_dim),
        "is_full_rank": bool(rank.is_full_rank),
        # JSON has no infinity literal. Keep the scientific state explicit and
        # make strict serialization reject any future unhandled non-finite value.
        "condition_number": round(condition_number, 6) if math.isfinite(condition_number) else None,
        "condition_number_is_finite": math.isfinite(condition_number),
        "measurable": bool(futility.measurability.passed),
        "oof_theta": round(float(futility.oof_theta), 12),
        "failures": [str(f) for f in futility.failures],
        "nonviable_candidates": [
            {"k_total": k, "lambda": lam, "reason": reason}
            for k, lam, reason in futility.nonviable_candidates
        ],
    }
    body["self_checksum"] = sha256_json({k: v for k, v in body.items() if k != "self_checksum"})
    path = Path(run_dir) / RUN_PRODUCED_BASENAMES["futility_report"]
    try:
        atomic_write_once(
            path,
            json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )
    except FileExistsError as exc:
        raise Phase2aSubcommandError(
            f"phase2a futility report already exists at {str(path)!r}; write-once"
        ) from exc
    return FUTILITY_EXIT
